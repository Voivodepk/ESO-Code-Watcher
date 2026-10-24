#!/usr/bin/env python3
"""Post newly discovered ESO promotion articles to Discord (unverified leads)."""
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

STATE = Path("seen_articles.json")
ATOM = "{http://www.w3.org/2005/Atom}"
PATTERN = re.compile(r"\b(code|codes|redeem|redemption|giveaway|free rewards?)\b", re.I)

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ESO-Code-Watcher/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()

def parse_articles(xml_bytes):
    root = ET.fromstring(xml_bytes)
    articles = []
    if root.tag.endswith("feed"):
        for entry in root.findall(f"{ATOM}entry"):
            title = entry.findtext(f"{ATOM}title", default="").strip()
            link_node = entry.find(f"{ATOM}link")
            link = link_node.get("href", "") if link_node is not None else ""
            guid = entry.findtext(f"{ATOM}id", default=link)
            articles.append((guid or link, title, link))
    else:
        for item in root.findall(".//item"):
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            guid = item.findtext("guid", default=link)
            articles.append((guid or link, title, link))
    return [(key, title, link) for key, title, link in articles if key and link.startswith(("https://", "http://"))]

def send(webhook, title, link):
    message = ("🐉 **ESO Reward Watch — Potential Announcement**\n"
               f"📰 **{title[:250]}**\n"
               f"🔗 {link}\n"
               "⚠️ Unverified article: check the source for an active redemption code.")
    data = json.dumps({"content": message, "allowed_mentions": {"parse": []}}).encode()
    request = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=25) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {response.status}")

def main():
    feed_url = os.environ.get("RSS_FEED_URL", "").strip()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not feed_url or not webhook:
        sys.exit("Missing RSS_FEED_URL or DISCORD_WEBHOOK_URL secret")
    articles = parse_articles(fetch(feed_url))
    if not articles:
        print("Feed has no articles; no changes.")
        return
    if STATE.exists():
        seen = set(json.loads(STATE.read_text()))
    else:
        # Initial run is a baseline: don't announce old articles.
        seen = {key for key, _, _ in articles}
        STATE.write_text(json.dumps(sorted(seen), indent=2) + "\n")
        print(f"Initialized baseline of {len(seen)} articles; no posts.")
        return
    count = 0
    for key, title, link in reversed(articles):
        if key in seen:
            continue
        if PATTERN.search(title):
            send(webhook, title, link)
            count += 1
        seen.add(key)
        STATE.write_text(json.dumps(sorted(seen), indent=2) + "\n")
    print(f"Posted {count} new candidate announcements.")

if __name__ == "__main__":
    main()

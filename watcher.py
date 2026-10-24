#!/usr/bin/env python3
"""Monitor Google Alerts and official ESO news for potential reward announcements."""
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

STATE = Path("seen_articles.json")
ATOM = "{http://www.w3.org/2005/Atom}"
OFFICIAL_URL = "https://www.elderscrollsonline.com/en-us/news"
PATTERN = re.compile(r"\b(code|codes|redeem|redemption|giveaway|free rewards?|claim.*rewards?)\b", re.I)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ESO-Code-Watcher/1.1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()

def rss_articles(data):
    root = ET.fromstring(data)
    articles = []
    if root.tag.endswith("feed"):
        for item in root.findall(f"{ATOM}entry"):
            title = item.findtext(f"{ATOM}title", default="").strip()
            link_element = item.find(f"{ATOM}link")
            link = link_element.get("href", "") if link_element is not None else ""
            key = item.findtext(f"{ATOM}id", default=link)
            articles.append(("rss:" + (key or link), title, link))
    else:
        for item in root.findall(".//item"):
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            key = item.findtext("guid", default=link)
            articles.append(("rss:" + (key or link), title, link))
    return [(key, title, link) for key, title, link in articles if link.startswith(("https://", "http://"))]

class NewsLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = {}
        self.active = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.active is not None:
            self.depth += 1
            return
        if tag != "a":
            return
        href = urljoin(OFFICIAL_URL, attrs.get("href", ""))
        parsed = urlparse(href)
        if parsed.hostname not in ("elderscrollsonline.com", "www.elderscrollsonline.com"):
            return
        if not re.match(r"^/en-us/news/post/", parsed.path):
            return
        self.active = [href.split("#")[0].split("?")[0], []]
        self.depth = 0

    def handle_data(self, data):
        if self.active is not None:
            self.active[1].append(data)

    def handle_endtag(self, tag):
        if self.active is None:
            return
        if self.depth:
            self.depth -= 1
        elif tag == "a":
            url, parts = self.active
            title = " ".join(" ".join(parts).split())
            if title:
                self.items[url] = title
            self.active = None

def official_articles(data):
    parser = NewsLinks()
    parser.feed(data.decode("utf-8", errors="replace"))
    return [("official:" + url, title, url) for url, title in parser.items.items()]

def send(webhook, title, link):
    message = ("🐉 **ESO Reward Watch — Potential Announcement**\n"
               f"📰 **{title[:250]}**\n"
               f"🔗 {link}\n"
               "⚠️ Unverified announcement: check the source for redemption details.")
    payload = json.dumps({"content": message, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=25) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {response.status}")

def main():
    feed = os.environ.get("RSS_FEED_URL", "").strip()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        sys.exit("Missing DISCORD_WEBHOOK_URL")
    if STATE.exists():
        seen = set(json.loads(STATE.read_text()))
        # Older script stored raw RSS IDs; preserve those as seen.
        seen |= {"rss:" + key for key in seen if not key.startswith(("rss:", "official:", "initialized:"))}
    else:
        seen = set()
    posted = 0
    sources_ok = 0
    for name, url, parser in [("rss", feed, rss_articles), ("official", OFFICIAL_URL, official_articles)]:
        if not url:
            print(f"{name}: no URL configured, skipping")
            continue
        try:
            articles = parser(fetch(url))
        except Exception as exc:
            print(f"WARNING: {name} unavailable: {type(exc).__name__}: {exc}")
            continue
        sources_ok += 1
        print(f"{name}: found {len(articles)} articles")
        marker = "initialized:" + name
        if marker not in seen:
            seen.update(key for key, _, _ in articles)
            seen.add(marker)
            print(f"{name}: initial baseline recorded; no historical posts")
            continue
        for key, title, link in reversed(articles):
            if key in seen:
                continue
            if PATTERN.search(title):
                send(webhook, title, link)
                posted += 1
            seen.add(key)
            STATE.write_text(json.dumps(sorted(seen), indent=2) + "\n")
    if not sources_ok:
        sys.exit("All sources failed; no updates")
    STATE.write_text(json.dumps(sorted(seen), indent=2) + "\n")
    print(f"Posted {posted} new candidate announcements.")

if __name__ == "__main__":
    main()

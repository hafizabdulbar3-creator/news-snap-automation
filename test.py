import json
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

RSS_URL = "https://data.gdeltproject.org/gdeltv3/gal/feed.rss"

HIGH_TRUST = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "cnn.com",
    "foxnews.com",
    "nbcnews.com",
    "cbsnews.com",
    "abcnews.go.com",
    "nytimes.com",
    "washingtonpost.com",
    "theguardian.com",
    "aljazeera.com",
    "dw.com",
    "france24.com",
    "npr.org",
    "bloomberg.com",
    "cnbc.com",
    "ft.com",
    "wsj.com",
    "economist.com",
    "hindustantimes.com",
    "indianexpress.com",
    "thehindu.com",
    "ndtv.com",
    "indiatoday.in",
    "timesofindia.indiatimes.com"
}

request = urllib.request.Request(
    RSS_URL,
    headers={"User-Agent": "NEWS-SNAP-Discovery/1.0"}
)

print("Fetching GDELT discovery feed...")

with urllib.request.urlopen(request, timeout=30) as response:
    xml_data = response.read()

root = ET.fromstring(xml_data)
items = root.findall(".//item")

articles = []
seen_urls = set()

for item in items:
    title = item.findtext("title", "").strip()
    url = item.findtext("link", "").strip()

    if not title or not url or url in seen_urls:
        continue

    seen_urls.add(url)

    domain = urlparse(url).netloc.lower().replace("www.", "")

    score = 0

    if domain in HIGH_TRUST:
        score += 100

    if any(word in title.lower() for word in [
        "president",
        "trump",
        "putin",
        "war",
        "attack",
        "election",
        "government",
        "economy",
        "market",
        "iran",
        "israel",
        "gaza",
        "ukraine",
        "russia",
        "china",
        "india",
        "nato",
        "united nations"
    ]):
        score += 20

    articles.append({
        "title": title,
        "url": url,
        "domain": domain,
        "score": score
    })

articles.sort(key=lambda x: x["score"], reverse=True)

with open("discovery.json", "w", encoding="utf-8") as file:
    json.dump(articles, file, ensure_ascii=False, indent=2)

print(f"Discovered {len(articles)} unique articles.")
print("\nTOP DISCOVERY CANDIDATES:\n")

for i, article in enumerate(articles[:20], start=1):
    print(f"{i}. [{article['score']}] {article['title']}")
    print(f"   {article['domain']}")
    print(f"   {article['url']}")
    print()

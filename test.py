import json
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

RSS_URL = "https://data.gdeltproject.org/gdeltv3/gal/feed.rss"

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

    domain = urlparse(url).netloc.replace("www.", "")

    articles.append({
        "title": title,
        "url": url,
        "domain": domain
    })

with open("discovery.json", "w", encoding="utf-8") as file:
    json.dump(articles, file, ensure_ascii=False, indent=2)

print(f"Discovered {len(articles)} unique articles.")

for i, article in enumerate(articles[:10], start=1):
    print(f"{i}. {article['title']}")
    print(f"   {article['domain']}")

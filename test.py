import urllib.request
import xml.etree.ElementTree as ET

RSS_URL = "https://data.gdeltproject.org/gdeltv3/gal/feed.rss"

request = urllib.request.Request(
    RSS_URL,
    headers={"User-Agent": "NEWS-SNAP-Automation/1.0"}
)

print("Fetching latest global news from GDELT RSS...")

with urllib.request.urlopen(request, timeout=30) as response:
    xml_data = response.read()

root = ET.fromstring(xml_data)

items = root.findall(".//item")

print(f"Found {len(items)} recent articles.")

for i, item in enumerate(items[:10], start=1):
    title = item.findtext("title", "No title")
    link = item.findtext("link", "No URL")

    print()
    print(f"{i}. {title}")
    print(f"   {link}")

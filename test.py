import json
import urllib.parse
import urllib.request

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

params = {
    "query": "*",
    "mode": "artlist",
    "format": "json",
    "maxrecords": "20",
    "timespan": "15min",
    "sort": "datedesc",
}

url = GDELT_URL + "?" + urllib.parse.urlencode(params)

print("Fetching latest global news from GDELT...")

with urllib.request.urlopen(url, timeout=30) as response:
    data = json.load(response)

articles = data.get("articles", [])

print(f"Found {len(articles)} articles.")

for i, article in enumerate(articles[:10], start=1):
    print(f"\n{i}. {article.get('title', 'No title')}")
    print(f"   Source: {article.get('domain', 'Unknown')}")
    print(f"   URL: {article.get('url', 'No URL')}")

with open("latest_news.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("\nSaved results to latest_news.json")

import json
import os
import urllib.request

MODEL = "gemini-3.5-flash-lite"
API_URL = (
    f"https://generativelanguage.googleapis.com/"
    f"v1beta/models/{MODEL}:generateContent"
)

BATCH_SIZE = 50


def call_gemini(articles):
    api_key = os.environ["GEMINI_API_KEY"]

    items = []
    for i, article in enumerate(articles):
        items.append({
            "id": i + 1,
            "title": article["title"],
            "source": article["domain"]
        })

    prompt = """You are the news-triage AI for NEWS SNAP.

Classify every article. DO NOT delete any article.

For each article return:
- id
- importance: MAJOR, NORMAL, or LOW
- topic: one short category
- reason: one short sentence

Use MAJOR for significant breaking news, major politics, wars,
international events, major disasters, major business/economic
developments, major technology launches, or other stories with broad
public importance.

Use NORMAL for legitimate but less important news.

Use LOW for local, trivial, duplicate-looking, obituary, lifestyle,
sports-only, entertainment-only, or otherwise low-impact stories.

Return ONLY valid JSON in this format:
{
  "results": [
    {
      "id": 1,
      "importance": "MAJOR",
      "topic": "Politics",
      "reason": "..."
    }
  ]
}

Articles:
""" + json.dumps(items, ensure_ascii=False)

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        },
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


with open("discovery.json", "r", encoding="utf-8") as file:
    articles = json.load(file)

batch = articles[:BATCH_SIZE]

print(f"Sending {len(batch)} articles to Gemini...")
result = call_gemini(batch)

with open("classified_sample.json", "w", encoding="utf-8") as file:
    json.dump(result, file, ensure_ascii=False, indent=2)

print("Gemini classification successful.")
print(f"Classified: {len(result.get('results', []))} articles")

for item in result.get("results", []):
    print(
        f"{item['id']}. "
        f"{item['importance']} | "
        f"{item['topic']} | "
        f"{item['reason']}"
    )

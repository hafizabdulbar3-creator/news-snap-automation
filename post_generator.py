import json
import os
import urllib.request

MODEL = "gemini-3.5-flash-lite"

API_URL = (
    "https://generativelanguage.googleapis.com/"
    f"v1beta/models/{MODEL}:generateContent"
)


def generate_post(article):
    api_key = os.environ["GEMINI_API_KEY"]

    prompt = f"""
You are the social-media editor for NEWS SNAP.

Create an Instagram-ready news post from the information below.

IMPORTANT:
- Do NOT invent facts.
- Do NOT add names, numbers, events, dates, quotes, locations,
  or claims that are not present in the supplied information.
- The article body has NOT been provided.
- Therefore, stay strictly within the supplied title, source,
  URL, and classification.
- Keep the wording factual and cautious.
- Do not copy the article title word-for-word if a cleaner headline
  can be made without changing its meaning.

Return ONLY valid JSON in exactly this structure:

{{
  "headline": "...",
  "curiosity_line": "...",
  "caption": "...",
  "hashtags": ["...", "...", "..."]
}}

NEWS INFORMATION:

Title: {article["title"]}
Source: {article["domain"]}
URL: {article["url"]}
Importance: {article.get("classification", {}).get("importance", "")}
Topic: {article.get("classification", {}).get("topic", "")}
Reason: {article.get("classification", {}).get("reason", "")}
"""

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


with open("selected_article.json", "r", encoding="utf-8") as file:
    article = json.load(file)

print("Generating NEWS SNAP post...")

post = generate_post(article)

with open("post.json", "w", encoding="utf-8") as file:
    json.dump(post, file, ensure_ascii=False, indent=2)

print("\nNEWS SNAP POST GENERATED\n")
print("HEADLINE:", post.get("headline", ""))
print("CURIOSITY:", post.get("curiosity_line", ""))
print("\nCAPTION:\n", post.get("caption", ""))
print("\nHASHTAGS:")
print(" ".join(post.get("hashtags", [])))

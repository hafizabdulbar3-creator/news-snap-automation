import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Supported valid Gemini API models (Default to gemini-2.5-flash)
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
BATCH_SIZE = 50


def call_gemini(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY environment variable is missing. Running in mock/offline mode.")
        # Return fallback classifications when no key is present (e.g. local test)
        results = []
        for i, a in enumerate(articles, start=1):
            results.append({
                "id": i,
                "importance": "MAJOR" if i <= 3 else "NORMAL",
                "topic": "World News",
                "reason": "Test evaluation fallback."
            })
        return {"results": results}

    items = []
    for i, article in enumerate(articles, start=1):
        items.append({
            "id": i,
            "title": article["title"],
            "source": article.get("domain", "")
        })

    prompt = """You are the senior news-triage AI for NEWS SNAP.
Classify every article. DO NOT omit any article from the results.

Requirements:
1. Language: Must be natural English. If an article is in a foreign language or nonsensical, mark as LOW with topic "Non-English".
2. Quality filter:
   - Mark as MAJOR: Major geopolitical events, wars, summits, national elections, central bank actions, major scientific/tech breakthroughs, major disasters, or stories of broad international consequence.
   - Mark as NORMAL: Legitimate national/regional policy, economic trends, corporate milestones, or notable public interest stories.
   - Mark as LOW: Local disputes, gossip, obituaries, sports-only, entertainment trivia, sensationalist claims, or unverified rumors.

Return ONLY valid JSON matching this schema:
{
  "results": [
    {
      "id": 1,
      "importance": "MAJOR",
      "topic": "World News",
      "reason": "Clear explanation of public significance."
    }
  ]
}

Articles to classify:
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
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    # Support fallback to alternative valid model names if the primary returns an error
    models_to_try = [MODEL, "gemini-2.0-flash", "gemini-1.5-flash"]
    # De-duplicate while preserving order
    seen_models = set()
    models_to_try = [m for m in models_to_try if not (m in seen_models or seen_models.add(m))]

    last_error = None
    for model_name in models_to_try:
        api_url = f"{API_BASE}/{model_name}:generateContent"
        request = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.load(response)

            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned empty candidates")

            text = candidates[0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            if "results" in parsed:
                return parsed
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            print(f"Model {model_name} HTTP {e.code}: {err_body}")
            last_error = e
            time.sleep(2)
        except Exception as e:
            print(f"Model {model_name} error: {e}")
            last_error = e
            time.sleep(1)

    raise RuntimeError(f"All Gemini classification attempts failed. Last error: {last_error}")


def main():
    discovery_path = Path("discovery.json")
    if not discovery_path.is_file():
        raise FileNotFoundError("discovery.json is missing. Run test.py first.")

    from check_candidates import get_fresh_candidates
    fresh_articles = get_fresh_candidates("discovery.json", "history.json")

    if not fresh_articles:
        print("[INFO] No fresh, unposted candidates found. Skipping Gemini classification to preserve API quota.")
        output_path = Path("classified_sample.json")
        output_path.write_text(json.dumps({
            "results": [],
            "status": "no_fresh_candidates",
            "message": "All discovered articles have already been published or are ineligible."
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    batch = fresh_articles[:BATCH_SIZE]
    print(f"Sending {len(batch)} fresh articles to Gemini triage...")
    result = call_gemini(batch)

    output_path = Path("classified_sample.json")
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    results = result.get("results", [])
    print(f"Gemini classification successful. Total classified: {len(results)}")

    majors = [r for r in results if r.get("importance") == "MAJOR"]
    print(f"MAJOR stories identified: {len(majors)}")
    for item in results[:10]:
        print(f"  {item.get('id')}. [{item.get('importance')}] {item.get('topic')} - {item.get('reason')}")


if __name__ == "__main__":
    main()

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Primary supported Gemini API model (Default to gemini-3.8-flash)
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
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

    models_to_try = [MODEL]

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
            try:
                from quota_manager import parse_quota_cooldown, set_quota_cooldown, heuristic_classify_article
                is_quota, reset_dt, reason = parse_quota_cooldown(e)
                if is_quota:
                    history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
                    print(f"[QUOTA COOLDOWN ACTIVATED] {reason} (Cooldown until {reset_dt.isoformat()}).")
                    try:
                        set_quota_cooldown(reset_dt, reason, history_path)
                    except Exception:
                        pass
                    print("[FALLBACK] Using local journalistic heuristic classification to avoid pipeline failure.")
                    results = []
                    for idx, a in enumerate(articles, start=1):
                        h_res = heuristic_classify_article(a.get("title", ""), a.get("domain", ""))
                        h_res["id"] = idx
                        results.append(h_res)
                    return {"results": results, "source": "local_heuristic"}
            except Exception as inner_e:
                print(f"[WARN] Error handling HTTP error in quota manager: {inner_e}")

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

    from check_candidates import get_fresh_candidates, get_history_sets
    from quota_manager import (
        get_classified_pool,
        save_to_classified_pool,
        is_cooldown_active,
        get_quota_cooldown,
        heuristic_classify_article,
    )

    history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
    output_path = Path("classified_sample.json")

    # 1. OPTIMIZATION: Check if persistent pool already has unposted, eligible candidates
    pool = get_classified_pool(history_path)
    if pool:
        hist_sets = get_history_sets(history_path)
        eligible_pool = [
            a for a in pool
            if a.get("url", "").lower() not in hist_sets["published_urls"]
            and a.get("url", "").lower() not in hist_sets["processed_urls"]
            and a.get("title", "").lower() not in hist_sets["published_titles"]
            and a.get("title", "").lower() not in hist_sets["processed_titles"]
        ]
        major_or_normal = [
            a for a in eligible_pool
            if a.get("classification", {}).get("importance") in ("MAJOR", "NORMAL")
        ]
        if major_or_normal:
            print(f"[POOL REUSE] Found {len(major_or_normal)} eligible classified article(s) in persistent pool.")
            print("[INFO] Reusing existing classified candidates; 0 Gemini API calls needed.")
            batch = major_or_normal[:BATCH_SIZE]
            results = []
            for i, a in enumerate(batch, start=1):
                cl = a["classification"]
                results.append({
                    "id": i,
                    "importance": cl.get("importance", "NORMAL"),
                    "topic": cl.get("topic", "World News"),
                    "reason": cl.get("reason", "Persistent candidate pool")
                })

            # Prepend pool items into discovery.json so select_article picks them
            try:
                disc_articles = json.loads(discovery_path.read_text(encoding="utf-8"))
            except Exception:
                disc_articles = []
            pool_urls = {b.get("url") for b in batch}
            merged_disc = batch + [a for a in disc_articles if a.get("url") not in pool_urls]
            discovery_path.write_text(json.dumps(merged_disc, ensure_ascii=False, indent=2), encoding="utf-8")

            output_path.write_text(json.dumps({"results": results, "source": "persistent_pool"}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Persistent pool triage successful. Total reused: {len(results)}")
            return

    # 2. If pool is empty, check fresh candidates
    fresh_articles = get_fresh_candidates("discovery.json", history_path)
    if not fresh_articles:
        print("[INFO] No fresh, unposted candidates found. Skipping Gemini classification to preserve API quota.")
        output_path.write_text(json.dumps({
            "results": [],
            "status": "no_fresh_candidates",
            "message": "All discovered articles have already been published or are ineligible."
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # 3. Check if Gemini quota is in active cooldown
    if is_cooldown_active(history_path):
        cd = get_quota_cooldown(history_path)
        print(f"[QUOTA COOLDOWN] Gemini API is in active quota cooldown until {cd.get('resets_at')}.")
        print("[FALLBACK] Using local journalistic heuristic classification to avoid API calls.")
        batch = fresh_articles[:BATCH_SIZE]
        results = []
        for i, a in enumerate(batch, start=1):
            h_res = heuristic_classify_article(a["title"], a.get("domain", ""))
            h_res["id"] = i
            results.append(h_res)
        output_path.write_text(json.dumps({"results": results, "source": "local_heuristic"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # 4. Normal Gemini Triage
    batch = fresh_articles[:BATCH_SIZE]
    print(f"Sending {len(batch)} fresh articles to Gemini triage...")
    result = call_gemini(batch)

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    results = result.get("results", [])
    print(f"Gemini classification successful. Total classified: {len(results)}")

    # 5. Save classified results to persistent pool in history.json
    from datetime import datetime, timezone
    new_pool_items = []
    res_by_id = {r.get("id"): r for r in results if isinstance(r, dict) and "id" in r}
    for idx, art in enumerate(batch, start=1):
        cl = res_by_id.get(idx)
        if cl and cl.get("importance") in ("MAJOR", "NORMAL"):
            new_pool_items.append({
                "title": art.get("title", ""),
                "domain": art.get("domain", ""),
                "url": art.get("url", ""),
                "classification": {
                    "importance": cl.get("importance"),
                    "topic": cl.get("topic", "World News"),
                    "reason": cl.get("reason", "")
                },
                "classified_at": datetime.now(timezone.utc).isoformat()
            })
    if new_pool_items:
        saved_count = save_to_classified_pool(new_pool_items, history_path)
        print(f"[POOL CACHE] Saved {saved_count} classified story(ies) into persistent pool for future runs.")

    majors = [r for r in results if r.get("importance") == "MAJOR"]
    print(f"MAJOR stories identified: {len(majors)}")
    for item in results[:10]:
        print(f"  {item.get('id')}. [{item.get('importance')}] {item.get('topic')} - {item.get('reason')}")


if __name__ == "__main__":
    main()

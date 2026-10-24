import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ai_provider import classify_articles_ai, get_active_provider

# Primary supported model defaults
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
BATCH_SIZE = 50


def call_ai(articles):
    """Classify articles via active AI provider (Groq or Gemini)."""
    try:
        return classify_articles_ai(articles)
    except urllib.error.HTTPError as e:
        try:
            from quota_manager import parse_quota_cooldown, set_quota_cooldown, heuristic_classify_article
            is_quota, reset_dt, reason = parse_quota_cooldown(e)
            if is_quota:
                history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
                provider = get_active_provider() or "ai"
                print(f"[QUOTA COOLDOWN ACTIVATED] {reason} (Cooldown until {reset_dt.isoformat()}).")
                try:
                    set_quota_cooldown(reset_dt, reason, history_path, provider=provider)
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
        raise e
    except Exception as e:
        # Any AI provider failure (e.g. 503, JSON parse, timeout, quota) safely falls back to heuristic triage
        print(f"[FALLBACK] AI classification unavailable ({e}). Using local journalistic heuristic classification to avoid pipeline failure.")
        try:
            from quota_manager import heuristic_classify_article
            results = []
            for idx, a in enumerate(articles, start=1):
                h_res = heuristic_classify_article(a.get("title", ""), a.get("domain", ""))
                h_res["id"] = idx
                results.append(h_res)
            return {"results": results, "source": "local_heuristic"}
        except Exception as inner_e:
            print(f"[FATAL] Local heuristic classification also failed: {inner_e}")
            raise e


# Maintain backwards compatibility
call_gemini = call_ai


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
            and (
                a.get("discovery_source") in ("jionews.com", "jionews")
                or ("discovery_source" not in a and a.get("discovery_source") != "gdelt")
            )
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

    # 3. Check if active AI provider quota is in active cooldown
    active_prov = get_active_provider() or None
    if is_cooldown_active(history_path, provider=active_prov):
        cd = get_quota_cooldown(history_path, provider=active_prov)
        prov_name = cd.get("provider", active_prov or "AI").upper()
        print(f"[QUOTA COOLDOWN] {prov_name} API is in active quota cooldown until {cd.get('resets_at')}.")
        print("[FALLBACK] Using local journalistic heuristic classification to avoid API calls.")
        batch = fresh_articles[:BATCH_SIZE]
        results = []
        for i, a in enumerate(batch, start=1):
            h_res = heuristic_classify_article(a["title"], a.get("domain", ""))
            h_res["id"] = i
            results.append(h_res)
        output_path.write_text(json.dumps({"results": results, "source": "local_heuristic"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # 4. Normal AI Triage (Groq or Gemini)
    batch = fresh_articles[:BATCH_SIZE]
    active_prov = get_active_provider() or "fallback"
    print(f"Sending {len(batch)} fresh articles to AI triage ({active_prov.upper()})...")
    result = call_ai(batch)

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    results = result.get("results", [])
    print(f"AI classification successful ({active_prov.upper()}). Total classified: {len(results)}")

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

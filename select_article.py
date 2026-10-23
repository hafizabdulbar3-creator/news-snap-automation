import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from source_allowlist import (
    is_approved_url,
    get_canonical_domain,
    check_topic_diversity,
    APPROVED_DOMAINS,
)

DEFAULT_RETENTION_HOURS = int(os.environ.get("DRY_RUN_RETENTION_HOURS", "48"))


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_genuine_article(title: str, url: str) -> bool:
    t_low = title.lower()
    if any(pat in t_low for pat in ("latest news & updates", "latest news and updates", "news archives", "category archives")):
        return False
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith(("/technology", "/world", "/business", "/politics", "/opinion", "/entertainment", "/energy-and-climate")):
        return False
    return True


def is_candidate_eligible(
    article: dict,
    classification: dict,
    recently_posted: set,
    recently_processed: set,
    posted_history: list
) -> tuple[bool, str]:
    """Strictly verify URL validity, approved whitelist domain, non-duplicate status, and topic diversity."""
    url = str(article.get("url", "")).strip()
    title = str(article.get("title", "")).strip()

    if not is_valid_url(url) or len(title.split()) < 4 or not is_genuine_article(title, url):
        return False, "invalid url structure or non-genuine article"

    # Absolute Domain Whitelist Enforcement
    if not is_approved_url(url):
        return False, f"url domain '{article.get('domain')}' not on approved news whitelist"

    url_low = url.lower()
    title_low = title.lower()
    if (url_low in recently_posted or title_low in recently_posted or
        url_low in recently_processed or title_low in recently_processed):
        return False, "duplicate (already posted or processed)"

    # Rolling Topic Diversity Safeguard: Max 2 posts per entity/topic in last 10 posts
    allowed, div_reason = check_topic_diversity(title, posted_history, max_same_topic=2, window_size=10)
    if not allowed:
        return False, div_reason

    return True, "eligible"


def select_best_article():
    discovery_path = Path("discovery.json")
    classified_path = Path("classified_sample.json")
    history_path = Path("history.json")

    if not discovery_path.is_file():
        raise FileNotFoundError("discovery.json is missing.")
    if not classified_path.is_file():
        raise FileNotFoundError("classified_sample.json is missing.")

    articles = json.loads(discovery_path.read_text(encoding="utf-8"))
    classified_data = json.loads(classified_path.read_text(encoding="utf-8"))

    # Load history (both published and recently dry-run-processed)
    recently_posted = set()
    recently_processed = set()
    posted_history = []
    if history_path.is_file():
        try:
            hist = json.loads(history_path.read_text(encoding="utf-8"))
            posted_history = hist.get("posted", [])
            for item in posted_history:
                if item.get("published") is True:
                    if item.get("url"):
                        recently_posted.add(item["url"].strip().lower())
                    if item.get("title"):
                        recently_posted.add(item["title"].strip().lower())

            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=DEFAULT_RETENTION_HOURS)
            for item in hist.get("processed", []):
                ts_str = item.get("timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue  # Expired
                    except Exception:
                        pass
                if item.get("url"):
                    recently_processed.add(item["url"].strip().lower())
                if item.get("title"):
                    recently_processed.add(item["title"].strip().lower())
        except Exception:
            pass

    classifications = {
        item["id"]: item
        for item in classified_data.get("results", [])
        if isinstance(item, dict) and "id" in item
    }

    selected = None

    # Pass 1: Look for MAJOR importance, approved whitelist domain, non-duplicate, diverse topic
    for index, article in enumerate(articles[:50], start=1):
        classification = classifications.get(index, {})
        eligible, reason = is_candidate_eligible(
            article, classification, recently_posted, recently_processed, posted_history
        )
        if not eligible:
            continue

        if classification.get("importance") == "MAJOR":
            topic = str(classification.get("topic", "")).lower()
            if "non-english" in topic or "foreign" in topic:
                continue
            selected = {**article, "classification": classification}
            break

    # Pass 2: If no MAJOR story found, look for NORMAL importance
    if selected is None:
        for index, article in enumerate(articles[:50], start=1):
            classification = classifications.get(index, {})
            eligible, reason = is_candidate_eligible(
                article, classification, recently_posted, recently_processed, posted_history
            )
            if not eligible:
                continue

            if classification.get("importance") == "NORMAL":
                topic = str(classification.get("topic", "")).lower()
                if "non-english" in topic or "foreign" in topic:
                    continue
                selected = {**article, "classification": classification}
                break

    # Pass 3: Fallback to the top valid approved non-duplicate diverse article
    if selected is None:
        for index, article in enumerate(articles[:50], start=1):
            classification = classifications.get(index, {})
            eligible, reason = is_candidate_eligible(
                article, classification, recently_posted, recently_processed, posted_history
            )
            if not eligible:
                continue

            selected = {**article, "classification": classification}
            break

    if selected is None:
        print("[INFO] No fresh, unposted article available for selection in this run.")
        sel_path = Path("selected_article.json")
        if sel_path.is_file():
            sel_path.unlink()
        return None

    # Clean up any stale roundup artifacts from prior runs/tests to prevent silent divergence
    for stale in (Path("roundup.json"), Path("roundup_post.json")):
        if stale.is_file():
            try:
                stale.unlink()
            except Exception:
                pass

    # Normalize canonical domain to verified approved source
    canonical_d = get_canonical_domain(selected.get("url", ""))
    if canonical_d:
        selected["domain"] = canonical_d

    Path("selected_article.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Prune unapproved stories from persistent classified_pool
    if history_path.is_file():
        try:
            raw_hist = json.loads(history_path.read_text(encoding="utf-8"))
            if "classified_pool" in raw_hist and isinstance(raw_hist["classified_pool"], list):
                orig_pool_len = len(raw_hist["classified_pool"])
                raw_hist["classified_pool"] = [
                    a for a in raw_hist["classified_pool"]
                    if isinstance(a, dict) and is_approved_url(a.get("url", ""))
                ]
                if len(raw_hist["classified_pool"]) != orig_pool_len:
                    history_path.write_text(json.dumps(raw_hist, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Preserve candidate in classified_pool until confirmed published or processed in instagram_publisher.py
    # This prevents dropping pool candidates if generation, rendering, or publishing fails downstream.

    print("SELECTED ARTICLE:")
    print(f"Title: {selected.get('title')}")
    print(f"Domain: {selected.get('domain')}")
    print(f"URL: {selected.get('url')}")
    print(f"Classification: {selected.get('classification')}")
    return selected


if __name__ == "__main__":
    select_best_article()

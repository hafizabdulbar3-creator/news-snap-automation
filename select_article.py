import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

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
    if history_path.is_file():
        try:
            hist = json.loads(history_path.read_text(encoding="utf-8"))
            for item in hist.get("posted", []):
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

    # Pass 1: Look for MAJOR importance, non-duplicate, valid English title
    for index, article in enumerate(articles[:50], start=1):
        url = article.get("url", "").strip()
        title = article.get("title", "").strip()
        classification = classifications.get(index, {})

        if not is_valid_url(url) or len(title.split()) < 4 or not is_genuine_article(title, url):
            continue

        if (url.lower() in recently_posted or title.lower() in recently_posted or
            url.lower() in recently_processed or title.lower() in recently_processed):
            continue

        if classification.get("importance") == "MAJOR":
            # Ensure it's not tagged as Non-English or trivial
            topic = str(classification.get("topic", "")).lower()
            if "non-english" in topic or "foreign" in topic:
                continue
            selected = {**article, "classification": classification}
            break

    # Pass 2: If no MAJOR story found, look for NORMAL importance
    if selected is None:
        for index, article in enumerate(articles[:50], start=1):
            url = article.get("url", "").strip()
            title = article.get("title", "").strip()
            classification = classifications.get(index, {})

            if not is_valid_url(url) or len(title.split()) < 4 or not is_genuine_article(title, url):
                continue

            if (url.lower() in recently_posted or title.lower() in recently_posted or
                url.lower() in recently_processed or title.lower() in recently_processed):
                continue

            if classification.get("importance") == "NORMAL":
                topic = str(classification.get("topic", "")).lower()
                if "non-english" in topic or "foreign" in topic:
                    continue
                selected = {**article, "classification": classification}
                break

    # Pass 3: Fallback to the top valid non-duplicate article
    if selected is None:
        for index, article in enumerate(articles[:50], start=1):
            url = article.get("url", "").strip()
            title = article.get("title", "").strip()
            classification = classifications.get(index, {})

            if not is_valid_url(url) or len(title.split()) < 4 or not is_genuine_article(title, url):
                continue

            if (url.lower() not in recently_posted and title.lower() not in recently_posted and
                url.lower() not in recently_processed and title.lower() not in recently_processed):
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

    Path("selected_article.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

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

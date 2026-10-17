"""NEWS SNAP Candidate Verification.

Checks discovered news candidates against history.json to ensure only genuinely fresh,
unposted, and un-processed articles are sent to Gemini API triage and post generation.
Prevents wasted API calls and prevents duplicate publications across 15-minute cycles.
Keeps published history and dry-run processed history separate.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

DISCOVERY_PATH = Path("discovery.json")
HISTORY_PATH = Path("history.json")

# Documented retention window for dry-run processed stories (48 hours by default)
DEFAULT_RETENTION_HOURS = int(os.environ.get("DRY_RUN_RETENTION_HOURS", "48"))


def is_valid_candidate_url(url: str) -> bool:
    """Validate that the candidate URL has a valid HTTP/HTTPS scheme and domain."""
    try:
        parsed = urlparse(str(url or "").strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_genuine_headline(title: str) -> bool:
    """Validate that the headline has enough content and is not a navigation/archive label."""
    t = str(title or "").strip()
    words = t.split()
    if len(words) < 4:
        return False
    t_low = t.lower()
    if any(pat in t_low for pat in ("latest news & updates", "latest news and updates", "news archives", "category archives")):
        return False
    return True


def get_history_sets(history_path=HISTORY_PATH, retention_hours: int = DEFAULT_RETENTION_HOURS) -> dict:
    """Extract sets of normalized lowercase URLs and titles for published and processed entries.

    Returns dict with keys:
    'published_urls', 'published_titles', 'processed_urls', 'processed_titles'
    """
    p = Path(history_path)
    res = {
        "published_urls": set(),
        "published_titles": set(),
        "processed_urls": set(),
        "processed_titles": set(),
    }
    if not p.is_file():
        return res

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=retention_hours)

    try:
        data = json.loads(p.read_text(encoding="utf-8"))

        # 1. Published entries in 'posted'
        for entry in data.get("posted", []):
            if entry.get("published") is True:
                u = str(entry.get("url", "")).strip().lower()
                t = str(entry.get("title", "")).strip().lower()
                if u:
                    res["published_urls"].add(u)
                if t:
                    res["published_titles"].add(t)

        # 2. Processed dry-run entries in 'processed' (within retention window)
        for entry in data.get("processed", []):
            ts_str = entry.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue  # Expired outside retention window
                except Exception:
                    pass
            u = str(entry.get("url", "")).strip().lower()
            t = str(entry.get("title", "")).strip().lower()
            if u:
                res["processed_urls"].add(u)
            if t:
                res["processed_titles"].add(t)
    except Exception:
        pass
    return res


def get_published_history(history_path=HISTORY_PATH) -> tuple[set, set]:
    """Extract sets of normalized lowercase URLs and titles that have been published."""
    sets = get_history_sets(history_path)
    return sets["published_urls"], sets["published_titles"]


def get_fresh_candidates(discovery_path=DISCOVERY_PATH, history_path=HISTORY_PATH, retention_hours: int = DEFAULT_RETENTION_HOURS) -> list:
    """Return all discovered articles that have NOT been published and NOT recently processed in dry-run.

    Does NOT fabricate stories, and does NOT discard unprocessed candidates.
    """
    disc_file = Path(discovery_path)
    if not disc_file.is_file():
        return []

    try:
        articles = json.loads(disc_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(articles, list):
        return []

    hist_sets = get_history_sets(history_path, retention_hours=retention_hours)

    fresh = []
    for article in articles:
        if not isinstance(article, dict):
            continue

        url = str(article.get("url", "")).strip()
        title = str(article.get("title", "")).strip()

        # Check duplicate flag from discovery
        if article.get("is_duplicate"):
            continue

        url_low = url.lower()
        title_low = title.lower()

        # Skip if already published to Instagram
        if url_low in hist_sets["published_urls"] or title_low in hist_sets["published_titles"]:
            continue

        # Skip if recently processed in dry-run mode within the retention window
        if url_low in hist_sets["processed_urls"] or title_low in hist_sets["processed_titles"]:
            continue

        if not is_valid_candidate_url(url) or not is_genuine_headline(title):
            continue

        fresh.append(article)

    return fresh


def main():
    fresh_articles = get_fresh_candidates()
    count = len(fresh_articles)
    has_fresh = count > 0

    print(f"Candidate check: {count} fresh eligible unposted article(s) found.")

    # Write GitHub Actions step output if running in CI
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        try:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"has_fresh={'true' if has_fresh else 'false'}\n")
                f.write(f"fresh_count={count}\n")
        except Exception as e:
            print(f"Warning: could not write to GITHUB_OUTPUT: {e}")

    if not has_fresh:
        print("[INFO] No fresh unposted eligible candidates in this cycle.")
        print("Downstream Gemini triage and post generation will be skipped to preserve API quota.")
        sys.exit(0)


if __name__ == "__main__":
    main()

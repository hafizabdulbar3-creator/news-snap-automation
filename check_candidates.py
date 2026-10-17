"""NEWS SNAP Candidate Verification.

Checks discovered news candidates against history.json to ensure only genuinely fresh,
unposted, and eligible articles are sent to Gemini API triage and post generation.
Prevents wasted API calls and prevents duplicate publications across 15-minute cycles.
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

DISCOVERY_PATH = Path("discovery.json")
HISTORY_PATH = Path("history.json")


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


def get_published_history(history_path=HISTORY_PATH) -> tuple[set, set]:
    """Extract sets of normalized lowercase URLs and titles that have been published."""
    p = Path(history_path)
    published_urls = set()
    published_titles = set()
    if not p.is_file():
        return published_urls, published_titles

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        for entry in data.get("posted", []):
            if entry.get("published") is True:
                u = str(entry.get("url", "")).strip().lower()
                t = str(entry.get("title", "")).strip().lower()
                if u:
                    published_urls.add(u)
                if t:
                    published_titles.add(t)
    except Exception:
        pass
    return published_urls, published_titles


def get_fresh_candidates(discovery_path=DISCOVERY_PATH, history_path=HISTORY_PATH) -> list:
    """Return all discovered articles that have NOT been published and meet eligibility criteria.

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

    published_urls, published_titles = get_published_history(history_path)

    fresh = []
    for article in articles:
        if not isinstance(article, dict):
            continue

        url = str(article.get("url", "")).strip()
        title = str(article.get("title", "")).strip()

        # Check duplicate flag from discovery or published history
        if article.get("is_duplicate"):
            continue

        if url.lower() in published_urls or title.lower() in published_titles:
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

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
    history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
    try:
        from quota_manager import are_all_configured_providers_cooling_down, get_quota_cooldown
        all_cooling, reason, earliest_reset = are_all_configured_providers_cooling_down(history_path)
        if all_cooling:
            resets_at = earliest_reset.isoformat() if earliest_reset else "scheduled reset"
            print(f"[QUOTA COOLDOWN] All configured free AI providers are in active quota cooldown until {resets_at}.")
            print(f"[REASON] {reason}")
            print("[INFO] Pausing automated pipeline executions to preserve system stability.")
            github_output = os.environ.get("GITHUB_OUTPUT")
            if github_output:
                try:
                    with open(github_output, "a", encoding="utf-8") as f:
                        f.write("has_fresh=false\n")
                        f.write("fresh_count=0\n")
                        f.write("cooldown_active=true\n")
                except Exception as e:
                    print(f"Warning: could not write to GITHUB_OUTPUT: {e}")
            sys.exit(0)
    except Exception as e:
        print(f"[QUOTA GUARD FAIL-CLOSED] Error checking quota cooldown: {e}")
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            try:
                with open(github_output, "a", encoding="utf-8") as f:
                    f.write("has_fresh=false\n")
                    f.write("fresh_count=0\n")
                    f.write("cooldown_active=true\n")
            except Exception:
                pass
        sys.exit(0)

    fresh_articles = get_fresh_candidates(history_path=history_path)

    # Also account for eligible unposted candidates in the persistent classified pool
    pool_eligible = []
    try:
        from quota_manager import (
            get_classified_pool,
            check_rolling_24h_cap,
            check_publication_cadence_due,
            DEFAULT_CADENCE_MINUTES,
            DEFAULT_MAX_ROLLING_POSTS_24H
        )
        pool = get_classified_pool(history_path)
        hist_sets = get_history_sets(history_path)
        pool_eligible = [
            a for a in pool
            if a.get("url", "").lower() not in hist_sets["published_urls"]
            and a.get("url", "").lower() not in hist_sets["processed_urls"]
            and a.get("title", "").lower() not in hist_sets["published_titles"]
            and a.get("title", "").lower() not in hist_sets["processed_titles"]
            and a.get("classification", {}).get("importance") in ("MAJOR", "NORMAL")
        ]
    except Exception:
        pool_eligible = []

    total_candidates = len(fresh_articles) + len(pool_eligible)

    # 1. Clear diagnostics for discovery, pool, and AI provider
    print(f"[NEWS DISCOVERY] News discovery completed: {len(fresh_articles)} fresh discovered article(s).")
    print(f"[QUEUE STATUS] Number of eligible queued stories in pool: {len(pool_eligible)} (Total candidate backlog: {total_candidates}).")
    active_provider = ""
    try:
        from ai_provider import get_active_provider
        active_provider = get_active_provider(history_path)
    except Exception:
        pass
    prov_label = (active_provider or "none").upper()
    print(f"[AI PROVIDER] Active provider: {prov_label}.")

    # 2. Check 50-post rolling 24-hour cap
    max_posts = int(os.environ.get("MAX_ROLLING_POSTS_24H", "50"))
    try:
        from quota_manager import check_rolling_24h_cap, check_publication_cadence_due, DEFAULT_CADENCE_MINUTES
        is_under_cap, count_24h, remaining_allowance = check_rolling_24h_cap(history_path, max_posts=max_posts)
    except Exception:
        is_under_cap, count_24h, remaining_allowance = True, 0, max_posts

    if not is_under_cap:
        print(f"[ROLLING 24H CAP REACHED] 50 confirmed posts published in the last 24 hours (Cap: {max_posts}). Publication paused until rolling window frees capacity.")
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            try:
                with open(github_output, "a", encoding="utf-8") as f:
                    f.write("has_fresh=false\n")
                    f.write("fresh_count=0\n")
                    f.write("cap_reached=true\n")
            except Exception:
                pass
        sys.exit(0)

    # 3. Check 25-minute publication cadence
    cadence_min = float(os.environ.get("PUBLISH_CADENCE_MINUTES", "25"))
    force_publish = os.environ.get("FORCE_PUBLISH", "").strip().lower() in ("true", "1", "yes")

    try:
        is_cadence_due, elapsed_min, remaining_min = check_publication_cadence_due(
            history_path, cadence_minutes=cadence_min
        )
    except Exception:
        is_cadence_due, elapsed_min, remaining_min = True, 999999.0, 0.0

    if not is_cadence_due and not force_publish:
        print(f"[CADENCE NOT DUE] Elapsed time since last confirmed post: {elapsed_min:.1f}m (Target: {cadence_min:.0f}m minimum). Next publication due in {remaining_min:.1f}m.")
        print(f"[CADENCE] News discovery preserved; skipping downstream AI triage, image generation, and publication to enforce {cadence_min:.0f}m minimum spacing.")
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            try:
                with open(github_output, "a", encoding="utf-8") as f:
                    f.write("has_fresh=false\n")
                    f.write("fresh_count=0\n")
                    f.write("cadence_due=false\n")
            except Exception:
                pass
        sys.exit(0)

    # 4. Cadence is due and cap is open
    print(f"[CADENCE OK] Publication cadence due ({elapsed_min:.1f}m >= {cadence_min:.0f}m) and rolling 24h cap allowance available ({remaining_allowance}/{max_posts}).")

    has_fresh = total_candidates > 0

    # Write GitHub Actions step output if running in CI
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        try:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"has_fresh={'true' if has_fresh else 'false'}\n")
                f.write(f"fresh_count={total_candidates}\n")
                f.write("cooldown_active=false\n")
                f.write("cadence_due=true\n")
                f.write("cap_reached=false\n")
        except Exception as e:
            print(f"Warning: could not write to GITHUB_OUTPUT: {e}")

    if not has_fresh:
        print("[INFO] No fresh unposted eligible candidates in this cycle.")
        print("[INFO] Skipping downstream generation; will not invent or recycle stories.")
        sys.exit(0)


if __name__ == "__main__":
    main()

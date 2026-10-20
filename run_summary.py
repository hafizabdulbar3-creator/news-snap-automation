"""NEWS SNAP - Comprehensive Run Outcome Summary.

Produces an explicit, human-readable banner in CI logs distinguishing:
1. Actual Instagram publications (with verified Media ID).
2. Dry-run completions.
3. Clean no-op runs due to active Gemini API quota cooldown.
4. Clean no-op runs due to lack of fresh candidates.

Prevents mistaking green no-op runs for live publications.
"""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path


def generate_run_summary(history_path: str = "history.json", discovery_path: str = "discovery.json") -> dict:
    hist_file = Path(history_path)
    disc_file = Path(discovery_path)
    post_file = Path("post.json")
    img_file = Path("news_snap_post.jpg")
    site_file = Path("_site/news_snap_post.jpg")
    selected_file = Path("selected_article.json")

    # 1. Candidates discovered
    discovered_count = 0
    if disc_file.is_file():
        try:
            disc_data = json.loads(disc_file.read_text(encoding="utf-8"))
            if isinstance(disc_data, list):
                discovered_count = len(disc_data)
        except Exception:
            pass

    # 2. Existing classified pool and cooldown
    pool_count = 0
    cooldown_active = False
    cooldown_reset = ""
    cooldown_reason = ""
    last_posted_entry = None

    if hist_file.is_file():
        try:
            hist_data = json.loads(hist_file.read_text(encoding="utf-8"))
            pool = hist_data.get("classified_pool", [])
            pool_count = len(pool) if isinstance(pool, list) else 0

            cd = hist_data.get("quota_cooldown", {})
            if cd.get("active"):
                resets_at_str = cd.get("resets_at", "")
                if resets_at_str:
                    try:
                        resets_at = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
                        if datetime.now(timezone.utc) < resets_at:
                            cooldown_active = True
                            cooldown_reset = resets_at_str
                            cooldown_reason = cd.get("reason", "")
                    except Exception:
                        pass

            posted = hist_data.get("posted", [])
            if posted and isinstance(posted, list):
                last_posted_entry = posted[-1]
        except Exception:
            pass

    # 3. Artifact generation checks
    image_generated = img_file.is_file() and img_file.stat().st_size > 15 * 1024
    image_size_kb = (img_file.stat().st_size / 1024) if image_generated else 0
    pages_deployed = site_file.is_file() and site_file.stat().st_size > 15 * 1024

    # 4. Publication confirmation check
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(minutes=15)
    confirmed_published = False
    published_media_id = None
    published_headline = None

    if last_posted_entry and last_posted_entry.get("published") is True:
        ts_str = last_posted_entry.get("timestamp")
        if ts_str:
            try:
                entry_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if entry_ts >= recent_cutoff:
                    # Verify it corresponds to the current selected article / post if present
                    curr_url = ""
                    if selected_file.is_file():
                        try:
                            sel = json.loads(selected_file.read_text(encoding="utf-8"))
                            curr_url = sel.get("url", "").strip().lower()
                        except Exception:
                            pass
                    entry_url = str(last_posted_entry.get("url", "")).strip().lower()
                    if not curr_url or curr_url == entry_url:
                        confirmed_published = True
                        published_media_id = last_posted_entry.get("media_id")
                        published_headline = last_posted_entry.get("headline") or last_posted_entry.get("title")
            except Exception:
                pass

    # 5. Check for recent safely rejected story
    recently_rejected = False
    rejection_reason = ""
    rejected_title = ""
    if hist_file.is_file():
        try:
            hist_data_full = json.loads(hist_file.read_text(encoding="utf-8"))
            processed_list = hist_data_full.get("processed", [])
            if processed_list and isinstance(processed_list, list):
                last_proc = processed_list[-1]
                if last_proc.get("rejected") is True:
                    ts_str = last_proc.get("timestamp")
                    if ts_str:
                        try:
                            entry_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if entry_ts >= recent_cutoff:
                                recently_rejected = True
                                rejection_reason = last_proc.get("rejection_reason", "Factual grounding validation refusal")
                                rejected_title = last_proc.get("title", "")
                        except Exception:
                            pass
        except Exception:
            pass

    # Determine primary run status label
    if confirmed_published:
        run_mode = "LIVE INSTAGRAM PUBLICATION CONFIRMED"
    elif cooldown_active:
        run_mode = "NO-OP: QUOTA COOLDOWN ACTIVE (PUBLICATION SUPPRESSED)"
    elif recently_rejected:
        run_mode = "STORY SAFELY REJECTED: FACTUAL GROUNDING SAFEGUARD ENFORCED"
    elif image_generated and not confirmed_published:
        run_mode = "DRY-RUN / PRE-FLIGHT COMPLETED (NO LIVE POST)"
    elif discovered_count == 0 and pool_count == 0:
        run_mode = "NO-OP: NO FRESH CANDIDATES DISCOVERED"
    else:
        run_mode = "NO-OP: PIPELINE SKIPPED DOWNSTREAM STEPS"

    summary = {
        "run_mode": run_mode,
        "discovered_count": discovered_count,
        "pool_count": pool_count,
        "cooldown_active": cooldown_active,
        "cooldown_reset": cooldown_reset,
        "cooldown_reason": cooldown_reason,
        "image_generated": image_generated,
        "image_size_kb": image_size_kb,
        "pages_deployed": pages_deployed,
        "confirmed_published": confirmed_published,
        "published_media_id": published_media_id,
        "published_headline": published_headline,
        "story_rejected": recently_rejected,
        "rejection_reason": rejection_reason,
        "rejected_title": rejected_title,
    }

    return summary


def print_run_summary(summary: dict) -> None:
    print("\n" + "=" * 78)
    print("                      NEWS SNAP WORKFLOW EXECUTION SUMMARY")
    print("=" * 78)
    print(f"RUN OUTCOME:                    {summary['run_mode']}")
    print("-" * 78)
    print(f"Candidates Discovered:          {summary['discovered_count']}")
    print(f"Classified Candidates in Pool:  {summary['pool_count']}")
    if summary['cooldown_active']:
        print(f"Generation Skipped (Cooldown):  YES")
        print(f"Cooldown Reset Time (UTC):      {summary['cooldown_reset']}")
        print(f"Cooldown Reason:                {summary['cooldown_reason']}")
    else:
        print(f"Generation Skipped (Cooldown):  NO (Quota Available)")

    img_status = f"YES ({summary['image_size_kb']:.1f} KB)" if summary['image_generated'] else "NO"
    print(f"New Image Generated:            {img_status}")
    print(f"GitHub Pages Deployed:          {'YES' if summary['pages_deployed'] else 'NO'}")

    if summary.get("story_rejected"):
        print(f"Story Rejected (Safeguard):     YES ({summary.get('rejected_title', '')[:50]})")
        print(f"Rejection Reason:               {summary.get('rejection_reason', '')}")
    else:
        print("Story Rejected (Safeguard):     NO")

    if summary['confirmed_published']:
        print(f"Instagram Confirmed Published:  YES (Media ID: {summary['published_media_id']})")
        print(f"Published Story Headline:       {summary['published_headline']}")
    else:
        print(f"Instagram Confirmed Published:  NO (No live post published in this run)")

    print("=" * 78 + "\n")


def main():
    history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
    summary = generate_run_summary(history_path=history_path)
    print_run_summary(summary)


if __name__ == "__main__":
    main()

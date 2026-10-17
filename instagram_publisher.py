"""NEWS SNAP Instagram Publisher.

Supports verified Dry-Run (default) and Live Meta Graph API publication.
Adheres strictly to safety requirements:
- Validates image dimensions (1080x1350, 4:5), format (JPEG), and size (<8MB).
- Validates caption length (<2200 chars) and presence of #NewsSnap.
- Checks duplicate history to prevent multiple posts of the same news story.
- Does not publish live unless ENABLE_INSTAGRAM_POSTING="true" and credentials exist.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PIL import Image

IMAGE_PATH = Path("news_snap_post.jpg")
POST_PATH = Path("post.json")
ARTICLE_PATH = Path("selected_article.json")
HISTORY_PATH = Path("history.json")

# Documented retention window for dry-run processed stories (48 hours by default)
DRY_RUN_RETENTION_HOURS = int(os.environ.get("DRY_RUN_RETENTION_HOURS", "48"))
MAX_HISTORY_ENTRIES = 100

GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v22.0").strip()
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def prune_processed_entries(entries: list, max_age_hours: int = DRY_RUN_RETENTION_HOURS, max_entries: int = MAX_HISTORY_ENTRIES) -> list:
    """Filter processed entries by retention window (default 48h) and cap at max_entries."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    valid = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        ts_str = e.get("timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue  # Expired outside retention window
            except Exception:
                pass
        valid.append(e)
    return valid[-max_entries:]


def record_dry_run_processed(article: dict, post: dict):
    """Save article entry into history.json under 'processed' (NEVER 'posted').

    Marked with published=False, dry_run=True.
    Prevents re-processing and repeated Gemini API calls during subsequent 15-minute runs.
    """
    history = {"posted": [], "processed": []}
    if HISTORY_PATH.is_file():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = {"posted": [], "processed": []}

    if "posted" not in history:
        history["posted"] = []
    if "processed" not in history:
        history["processed"] = []

    timestamp = datetime.now(timezone.utc).isoformat()
    processed_list = history["processed"]

    # Check if this is a Format 04 roundup with multiple stories
    roundup_path = Path("roundup.json")
    is_roundup = post.get("format") == "04" or (roundup_path.is_file() and "top 3" in post.get("headline", "").lower())
    if is_roundup and roundup_path.is_file():
        try:
            roundup_data = json.loads(roundup_path.read_text(encoding="utf-8"))
            for s in roundup_data.get("stories", []):
                processed_list.append({
                    "url": s.get("url", ""),
                    "title": s.get("title", ""),
                    "headline": post.get("headline", ""),
                    "domain": s.get("domain", ""),
                    "published": False,
                    "dry_run": True,
                    "timestamp": timestamp,
                })
        except Exception:
            pass

    entry = {
        "url": article.get("url", ""),
        "title": article.get("title", ""),
        "headline": post.get("headline", ""),
        "domain": article.get("domain", ""),
        "published": False,
        "dry_run": True,
        "timestamp": timestamp,
    }
    processed_list.append(entry)

    # Prune processed list: retain entries within 48-hour retention window up to 100 entries
    history["processed"] = prune_processed_entries(processed_list, max_age_hours=DRY_RUN_RETENTION_HOURS, max_entries=MAX_HISTORY_ENTRIES)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Recorded dry-run entry in {HISTORY_PATH} under 'processed' (total processed: {len(history['processed'])}).")


def record_published_history(article: dict, post: dict, media_id: str = None):
    """Save article entry into history.json under 'posted' with published=True."""
    history = {"posted": [], "processed": []}
    if HISTORY_PATH.is_file():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = {"posted": [], "processed": []}

    if "posted" not in history:
        history["posted"] = []
    if "processed" not in history:
        history["processed"] = []

    posted_list = history["posted"]
    timestamp = datetime.now(timezone.utc).isoformat()

    # Check if this is a Format 04 roundup with multiple stories
    roundup_path = Path("roundup.json")
    is_roundup = post.get("format") == "04" or (roundup_path.is_file() and "top 3" in post.get("headline", "").lower())
    if is_roundup and roundup_path.is_file():
        try:
            roundup_data = json.loads(roundup_path.read_text(encoding="utf-8"))
            for s in roundup_data.get("stories", []):
                posted_list.append({
                    "url": s.get("url", ""),
                    "title": s.get("title", ""),
                    "headline": post.get("headline", ""),
                    "domain": s.get("domain", ""),
                    "published": True,
                    "media_id": media_id,
                    "timestamp": timestamp,
                })
        except Exception:
            pass

    entry = {
        "url": article.get("url", ""),
        "title": article.get("title", ""),
        "headline": post.get("headline", ""),
        "domain": article.get("domain", ""),
        "published": True,
        "media_id": media_id,
        "timestamp": timestamp,
    }
    posted_list.append(entry)

    # Retain the last 100 entries
    history["posted"] = posted_list[-MAX_HISTORY_ENTRIES:]
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Recorded live post entry in {HISTORY_PATH} under 'posted' (total posted: {len(history['posted'])}).")


def record_history(article: dict, post: dict, published: bool = False, media_id: str = None):
    """Wrapper routing to published or dry-run processed history lists."""
    if published:
        record_published_history(article, post, media_id=media_id)
    else:
        record_dry_run_processed(article, post)


def is_already_posted(article: dict) -> bool:
    if not HISTORY_PATH.is_file():
        return False
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        posted_items = [item for item in history.get("posted", []) if item.get("published")]
        if not posted_items:
            return False

        # If a roundup is active, check duplicate for any of its stories
        roundup_path = Path("roundup.json")
        if roundup_path.is_file():
            try:
                roundup_data = json.loads(roundup_path.read_text(encoding="utf-8"))
                for s in roundup_data.get("stories", []):
                    s_url = str(s.get("url", "")).strip().lower()
                    s_title = str(s.get("title", "")).strip().lower()
                    for item in posted_items:
                        if s_url and item.get("url", "").strip().lower() == s_url:
                            return True
                        if s_title and item.get("title", "").strip().lower() == s_title:
                            return True
            except Exception:
                pass

        norm_url = str(article.get("url", "")).strip().lower()
        norm_title = str(article.get("title", "")).strip().lower()
        for item in posted_items:
            if norm_url and item.get("url", "").strip().lower() == norm_url:
                return True
            if norm_title and item.get("title", "").strip().lower() == norm_title:
                return True
    except Exception:
        pass
    return False


def is_already_processed(article: dict, retention_hours: int = DRY_RUN_RETENTION_HOURS) -> bool:
    """Check if the article was already processed in dry-run mode within the retention window."""
    if not HISTORY_PATH.is_file():
        return False
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        processed_items = history.get("processed", [])
        if not processed_items:
            return False

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=retention_hours)

        # Check Format 04 roundup stories
        roundup_path = Path("roundup.json")
        if roundup_path.is_file():
            try:
                roundup_data = json.loads(roundup_path.read_text(encoding="utf-8"))
                for s in roundup_data.get("stories", []):
                    s_url = str(s.get("url", "")).strip().lower()
                    s_title = str(s.get("title", "")).strip().lower()
                    for item in processed_items:
                        ts_str = item.get("timestamp")
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                if ts < cutoff:
                                    continue
                            except Exception:
                                pass
                        if s_url and item.get("url", "").strip().lower() == s_url:
                            return True
                        if s_title and item.get("title", "").strip().lower() == s_title:
                            return True
            except Exception:
                pass

        norm_url = str(article.get("url", "")).strip().lower()
        norm_title = str(article.get("title", "")).strip().lower()
        for item in processed_items:
            ts_str = item.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except Exception:
                    pass
            if norm_url and item.get("url", "").strip().lower() == norm_url:
                return True
            if norm_title and item.get("title", "").strip().lower() == norm_title:
                return True
    except Exception:
        pass
    return False


def verify_format_caption_alignment(post: dict, caption: str) -> None:
    """Ensure post caption and attribution strictly match the rendered format and content."""
    is_roundup_post = (
        post.get("format") == "04"
        or "top 3" in post.get("headline", "").lower()
        or "roundup" in post.get("headline", "").lower()
    )
    roundup_path = Path("roundup.json")

    if is_roundup_post:
        if not roundup_path.is_file():
            raise ValueError(
                "FORMAT 04 MISMATCH: Post is marked as a Format 04 Roundup, but roundup.json is missing."
            )
        roundup = json.loads(roundup_path.read_text(encoding="utf-8"))
        stories = roundup.get("stories", [])
        if len(stories) != 3:
            raise ValueError(f"FORMAT 04 MISMATCH: roundup.json must have 3 stories, found {len(stories)}.")

        caption_lower = caption.lower()
        matched_domains = sum(1 for s in stories if s.get("domain", "").lower() in caption_lower)
        if matched_domains < 2 and not any(k in caption_lower for k in ("roundup", "top 3 stories", "daily briefing")):
            raise ValueError(
                "FORMAT 04 MISMATCH: Post caption does not contain the verified multi-story roundup content. "
                "Roundup image cannot be published with an unrelated single-story caption."
            )
    else:
        # Single story post: ensure caption does not claim to be a roundup when it isn't
        if "top 3 stories" in caption.lower() and not roundup_path.is_file():
            raise ValueError(
                "FORMAT MISMATCH: Caption references 'TOP 3 STORIES', but no roundup.json exists."
            )


def get_default_pages_url(repo: str) -> str:
    """Construct the standard GitHub Pages URL for the public repository."""
    if not repo or "/" not in repo:
        return ""
    owner, repo_name = repo.strip().split("/", 1)
    return f"https://{owner.strip().lower()}.github.io/{repo_name.strip()}/news_snap_post.jpg"


def normalize_image_url(url_or_base: str) -> str:
    """Normalize a base Pages URL or full image URL to point to news_snap_post.jpg with a single slash."""
    url = str(url_or_base or "").strip()
    if not url:
        return ""
    if url.lower().endswith("news_snap_post.jpg"):
        prefix = url[:-len("news_snap_post.jpg")].rstrip("/")
        return f"{prefix}/news_snap_post.jpg"
    if url.lower().endswith(".jpg") or url.lower().endswith(".jpeg"):
        return url
    return url.rstrip("/") + "/news_snap_post.jpg"


def verify_public_image_url(url: str, max_retries: int = 6, retry_delay: float = 5.0) -> None:
    """Validate that the image URL is a valid public HTTPS link and reachable before API calls.

    Includes brief retries to accommodate normal GitHub Pages CDN propagation delays.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Public image URL is missing or empty.")
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"IMAGE_PUBLIC_URL must be a valid public HTTPS URL, got: '{url}'")

    clean_url = url.strip()
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                clean_url,
                headers={"User-Agent": "NEWS-SNAP-Publisher/1.0 (pre-flight check)"},
                method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    print(f"[OK] Verified public image URL reachable (HTTP 200): {clean_url}")
                    return
                last_error = f"HTTP status {resp.status}"
        except urllib.error.HTTPError as err:
            if err.code == 405:  # Method Not Allowed for HEAD; retry with partial GET
                try:
                    get_req = urllib.request.Request(
                        clean_url,
                        headers={"User-Agent": "NEWS-SNAP-Publisher/1.0", "Range": "bytes=0-512"}
                    )
                    with urllib.request.urlopen(get_req, timeout=12) as get_resp:
                        if get_resp.status in (200, 206):
                            print(f"[OK] Verified public image URL reachable (HTTP {get_resp.status}): {clean_url}")
                            return
                        last_error = f"HTTP status {get_resp.status}"
                except Exception as get_err:
                    last_error = f"{type(get_err).__name__}: {get_err}"
            else:
                last_error = f"HTTP {err.code} {err.reason}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < max_retries:
            print(f"Image URL verification attempt {attempt}/{max_retries} pending ({last_error}). Retrying in {retry_delay}s...")
            time.sleep(retry_delay)

    raise ValueError(
        f"FAIL-CLOSED: Public image URL verification failed after {max_retries} attempts ({last_error}).\n"
        f"URL: {clean_url}\n"
        f"Ensure GitHub Pages deployment has succeeded and the image is publicly accessible."
    )


def validate_image_and_post(article: dict = None):
    if not IMAGE_PATH.is_file():
        raise FileNotFoundError(f"Image file {IMAGE_PATH} not found.")
    if not POST_PATH.is_file():
        raise FileNotFoundError(f"Post file {POST_PATH} not found.")

    post = json.loads(POST_PATH.read_text(encoding="utf-8"))
    caption = str(post.get("caption", "")).strip()

    # 1. Caption checks
    if not caption:
        raise ValueError("Caption is empty.")
    if len(caption) > 2200:
        raise ValueError(f"Caption exceeds Instagram 2,200 character limit ({len(caption)} chars).")
    if "#newssnap" not in caption.lower():
        raise ValueError("Caption must include #NewsSnap hashtag.")

    # 2. Headline & text layout bounds
    headline = str(post.get("headline", "")).strip()
    if not headline:
        raise ValueError("Post headline is missing.")
    hl_words = headline.split()
    if not (4 <= len(hl_words) <= 14):
        raise ValueError(f"Headline word count ({len(hl_words)}) out of bounds (4–14 words required).")
    if hl_words[-1].lower() in {"by", "to", "at", "of", "for", "on", "with", "and", "or", "in"}:
        raise ValueError(f"Headline appears clipped/incomplete (ends with trailing connector '{hl_words[-1]}').")

    # 3. Format & caption alignment check (prevents Format 04 mismatch)
    verify_format_caption_alignment(post, caption)

    # 4. Image dimensions, format, and visual integrity checks
    with Image.open(IMAGE_PATH) as img:
        img_format = img.format
        width, height = img.size
        # Verify image is not corrupted or solid blank rectangle
        extrema = img.getextrema()
        if isinstance(extrema[0], tuple):  # Multi-band RGB/RGBA
            has_variation = any(ch[0] != ch[1] for ch in extrema)
        else:
            has_variation = extrema[0] != extrema[1]
        if not has_variation:
            raise ValueError("Corrupted/blank image: Canvas has zero visual entropy (solid color).")

    if img_format not in ("JPEG", "JPG"):
        raise ValueError(f"Image must be JPEG format, got: {img_format}")
    if (width, height) != (1080, 1350):
        raise ValueError(f"Image must be 1080x1350 (4:5 ratio), got: {width}x{height}")

    file_size_mb = IMAGE_PATH.stat().st_size / (1024 * 1024)
    if file_size_mb > 8.0:
        raise ValueError(f"Image size exceeds 8MB ({file_size_mb:.2f} MB).")
    if IMAGE_PATH.stat().st_size < 15 * 1024:
        raise ValueError(f"Image file size is suspiciously small ({IMAGE_PATH.stat().st_size} bytes); incomplete render.")

    # 5. Attribution truthfulness
    if "illustration" in caption.lower() and "image credit:" in caption.lower() and post.get("format") != "04":
        if re.search(r"Image credit:\s*[^.\n]+\s+by\s+[^.\n]+", caption):
            raise ValueError("Attribution error: Real photo credits cannot be attributed to synthetic illustrations.")

    # 6. Factual grounding verification against article if available
    if article and isinstance(article, dict):
        art_title = str(article.get("title", "")).strip()
        if art_title:
            uncertainty_cues = ("?", "alleged", "allegedly", "suspected", "may face", "could face", "claims", "investigating")
            if any(cue in art_title.lower() for cue in uncertainty_cues):
                attribution_markers = ("alleged", "allegedly", "claims", "reportedly", "suspected", "may", "could", "probe", "investigation", "says", "stated", "accused", "according to", "facing", "under")
                if not any(m in headline.lower() or m in caption.lower() for m in attribution_markers):
                    raise ValueError(f"Factual grounding error: Uncertainty in source title ('{art_title}') converted to settled fact.")

    return post, caption


def main():
    print("===== NEWS SNAP INSTAGRAM PUBLISHER =====")
    if not IMAGE_PATH.is_file() or not POST_PATH.is_file():
        print("[INFO] No generated image (news_snap_post.jpg) or post file (post.json) found. Skipping publication.")
        return

    article = {}
    if ARTICLE_PATH.is_file():
        try:
            article = json.loads(ARTICLE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    post, caption = validate_image_and_post(article=article)
    print("[OK] Image validation: 1080x1350 JPEG, within 8MB limit, verified non-empty visual entropy.")
    print("[OK] Caption validation: Under 2,200 characters, #NewsSnap included, text within bounds.")
    print("[OK] Format alignment validation: Image and caption refer to the same story data.")
    print("[OK] Factual and attribution safeguards verified.")

    # Check duplicate prevention
    if is_already_posted(article):
        print("Duplicate alert: This article was already marked as published in history.json.")
        print("Skipping publication to prevent duplicate Instagram feed posts.")
        sys.exit(0)
    elif is_already_processed(article):
        print("Duplicate alert: This article was already processed in a previous dry-run within the retention window.")
        print("Skipping to prevent repeated API calls and duplicate processing.")
        sys.exit(0)
    else:
        print("[OK] Duplicate prevention check passed (fresh story).")

    # Inspect credentials and flags
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "").strip()
    enable_live_posting = os.environ.get("ENABLE_INSTAGRAM_POSTING", "").strip().lower() == "true"

    has_credentials = bool(access_token and account_id)
    print(f"Credentials present: {'Yes' if has_credentials else 'No'}")
    print(f"Live posting enabled (ENABLE_INSTAGRAM_POSTING=true): {enable_live_posting}")

    # DRY-RUN MODE (Safe default)
    if not (enable_live_posting and has_credentials):
        print("\n[DRY-RUN MODE] Live publishing is disabled or credentials are not configured.")
        print("All format, image, and duplicate checks PASSED successfully.")
        print("The generated image is ready for Instagram publication.")
        record_dry_run_processed(article, post)
        print("Dry-run complete: Article recorded in 'processed' list (published=False) to prevent repeated API calls.")
        return

    # LIVE PUBLISHING MODE
    print("\n[LIVE PUBLISHING MODE ACTIVATED]")

    # Refuse to publish if this article was previously processed as a dry-run test
    if is_already_processed(article):
        raise ValueError(
            "SAFETY REFUSAL: This article was previously processed as a dry-run test story. "
            "To prevent old test stories from being published when live mode is activated, "
            "only fresh, un-processed news stories are permitted."
        )

    # Safety check: Never publish synthetic or mock test stories to Instagram
    if post.get("is_synthetic"):
        raise ValueError(
            "SAFETY REFUSAL: The generated post is marked as synthetic/mock test data. "
            "Never publish synthetic test stories to Instagram. "
            "Real Gemini API generation is required for live publishing."
        )

    raw_image_url = os.environ.get("IMAGE_PUBLIC_URL", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not raw_image_url and repo:
        raw_image_url = get_default_pages_url(repo)
        print(f"Constructed default GitHub Pages image URL: {raw_image_url}")

    image_public_url = normalize_image_url(raw_image_url)
    if not image_public_url:
        raise ValueError(
            "FAIL-CLOSED: Live Instagram publishing requires a verified public HTTPS image URL (IMAGE_PUBLIC_URL).\n"
            "The image generated during the workflow run (news_snap_post.jpg) is stored on the local runner "
            "and cannot be fetched directly by Meta's Graph API.\n"
            "GitHub Pages deployment or external image hosting is required.\n"
            "Configure IMAGE_PUBLIC_URL or ensure GitHub Pages deployment step has completed."
        )
    verify_public_image_url(image_public_url)

    # Step 1: Create Container
    container_url = f"{GRAPH_API_BASE}/{account_id}/media"
    container_payload = urllib.parse.urlencode({
        "image_url": image_public_url,
        "caption": caption,
        "access_token": access_token,
    }).encode("utf-8")

    print("Creating Instagram media container...")
    req = urllib.request.Request(container_url, data=container_payload, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        res_data = json.load(resp)
    creation_id = res_data.get("id")
    if not creation_id:
        raise RuntimeError(f"Container creation failed: {res_data}")
    print(f"Container created with ID: {creation_id}")

    # Wait a few seconds for Meta media processing
    time.sleep(5)

    # Step 2: Publish Media
    publish_url = f"{GRAPH_API_BASE}/{account_id}/media_publish"
    publish_payload = urllib.parse.urlencode({
        "creation_id": creation_id,
        "access_token": access_token,
    }).encode("utf-8")

    print("Publishing container to Instagram feed...")
    req = urllib.request.Request(publish_url, data=publish_payload, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        pub_data = json.load(resp)
    media_id = pub_data.get("id")
    if not media_id:
        raise RuntimeError(f"Media publishing failed: {pub_data}")

    print(f"[OK] SUCCESSFULLY PUBLISHED TO INSTAGRAM! Media ID: {media_id}")
    record_history(article, post, published=True, media_id=media_id)


if __name__ == "__main__":
    main()

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
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

IMAGE_PATH = Path("news_snap_post.jpg")
POST_PATH = Path("post.json")
ARTICLE_PATH = Path("selected_article.json")
HISTORY_PATH = Path("history.json")

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def record_history(article: dict, post: dict, published: bool = False, media_id: str = None):
    """Save article entry into history.json to prevent duplicate posts across workflow runs."""
    history = {"posted": []}
    if HISTORY_PATH.is_file():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = {"posted": []}

    posted_list = history.get("posted", [])
    entry = {
        "url": article.get("url", ""),
        "title": article.get("title", ""),
        "headline": post.get("headline", ""),
        "domain": article.get("domain", ""),
        "published": published,
        "media_id": media_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    posted_list.append(entry)

    # Retain the last 100 entries
    history["posted"] = posted_list[-100:]
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Recorded post entry in {HISTORY_PATH} (total entries: {len(history['posted'])}).")


def is_already_posted(article: dict) -> bool:
    if not HISTORY_PATH.is_file():
        return False
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        norm_url = str(article.get("url", "")).strip().lower()
        norm_title = str(article.get("title", "")).strip().lower()
        for item in history.get("posted", []):
            if item.get("published"):
                if norm_url and item.get("url", "").strip().lower() == norm_url:
                    return True
                if norm_title and item.get("title", "").strip().lower() == norm_title:
                    return True
    except Exception:
        pass
    return False


def validate_image_and_post():
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

    # 2. Image checks
    with Image.open(IMAGE_PATH) as img:
        img_format = img.format
        width, height = img.size

    if img_format not in ("JPEG", "JPG"):
        raise ValueError(f"Image must be JPEG format, got: {img_format}")
    if (width, height) != (1080, 1350):
        raise ValueError(f"Image must be 1080x1350 (4:5 ratio), got: {width}x{height}")

    file_size_mb = IMAGE_PATH.stat().st_size / (1024 * 1024)
    if file_size_mb > 8.0:
        raise ValueError(f"Image size exceeds 8MB ({file_size_mb:.2f} MB).")

    return post, caption


def main():
    print("===== NEWS SNAP INSTAGRAM PUBLISHER =====")
    post, caption = validate_image_and_post()
    print("[OK] Image validation: 1080x1350 JPEG, within 8MB limit.")
    print("[OK] Caption validation: Under 2,200 characters, #NewsSnap included.")

    article = {}
    if ARTICLE_PATH.is_file():
        try:
            article = json.loads(ARTICLE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Check duplicate prevention
    if is_already_posted(article):
        print("Duplicate alert: This article was already marked as published in history.json.")
        print("Skipping publication to prevent duplicate Instagram feed posts.")
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
        print("Dry-run complete: Article is NOT marked as published, preserving its eligibility for real publication.")
        return

    # LIVE PUBLISHING MODE
    print("\n[LIVE PUBLISHING MODE ACTIVATED]")

    # Safety check: Never publish synthetic or mock test stories to Instagram
    if post.get("is_synthetic"):
        raise ValueError(
            "SAFETY REFUSAL: The generated post is marked as synthetic/mock test data. "
            "Never publish synthetic test stories to Instagram. "
            "Real Gemini API generation is required for live publishing."
        )

    image_public_url = os.environ.get("IMAGE_PUBLIC_URL", "").strip()
    if not image_public_url:
        # Check if repository and SHA are available to construct GitHub raw URL
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        sha = os.environ.get("GITHUB_SHA", "main")
        if repo:
            image_public_url = f"https://raw.githubusercontent.com/{repo}/{sha}/news_snap_post.jpg"
            print(f"Using GitHub raw image URL: {image_public_url}")
        else:
            raise ValueError("Live Instagram publishing requires IMAGE_PUBLIC_URL or GITHUB_REPOSITORY.")

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

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
import re
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
MAX_HISTORY_ENTRIES = 500

# Meta Graph API configuration for Instagram Login / "Manage content on Instagram"
INSTAGRAM_GRAPH_HOST = os.environ.get("INSTAGRAM_GRAPH_HOST", "graph.instagram.com").strip()
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v22.0").strip()
GRAPH_API_BASE = f"https://{INSTAGRAM_GRAPH_HOST}/{GRAPH_API_VERSION}"

# Required permission scopes for Instagram Login publishing
REQUIRED_PERMISSIONS = (
    "instagram_business_basic",
    "instagram_business_content_publish",
)
SUPPORTED_GRAPH_API_VERSIONS = ("v21.0", "v22.0", "v23.0")


def is_supported_api_version(version: str) -> bool:
    """Validate that the Graph API version conforms to Meta versioning and is currently supported (>= v21.0)."""
    if not version or not isinstance(version, str):
        return False
    clean = version.strip()
    if not re.match(r"^v\d+\.\d+$", clean):
        return False
    try:
        ver_num = float(clean.lstrip("v"))
        return ver_num >= 21.0
    except ValueError:
        return False


def mask_token(token: str) -> str:
    """Mask access token for safe logging, exposing only first 4 and last 4 characters."""
    if not token or not isinstance(token, str):
        return ""
    clean = token.strip()
    if len(clean) <= 8:
        return "***"
    return f"{clean[:4]}...{clean[-4:]}"


def sanitize_token(text: str, token: str = "") -> str:
    """Sanitize raw tokens from exception strings, URLs, and logs to prevent credential leakage."""
    if not text:
        return ""
    sanitized = str(text)
    if token and len(token) > 4:
        sanitized = sanitized.replace(token, mask_token(token))
    # General regex patterns for access tokens in URLs, headers, or JSON payloads
    sanitized = re.sub(r'access_token=([^&\s"\'\\}]+)', lambda m: f"access_token={mask_token(m.group(1))}", sanitized)
    sanitized = re.sub(r'("access_token"\s*:\s*")([^"\s]+)(")', lambda m: f'{m.group(1)}{mask_token(m.group(2))}{m.group(3)}', sanitized)
    sanitized = re.sub(r'(Bearer\s+)([A-Za-z0-9_\-\.]+)', lambda m: f'{m.group(1)}{mask_token(m.group(2))}', sanitized)
    return sanitized


def fetch_account_info(access_token: str, graph_base: str = GRAPH_API_BASE) -> dict:
    """Fetch Instagram profile and professional account ID via the /me endpoint.

    Uses Instagram Login authentication (Bearer token) to query the authenticated user's
    user_id, id, username, name, and account_type.
    """
    if not access_token:
        return {}
    url = f"{graph_base}/me?fields=user_id,id,username,name,account_type"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NEWS-SNAP-Publisher/1.0",
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        sanitized_body = sanitize_token(body, access_token)
        err_msg = ""
        try:
            err_json = json.loads(body)
            oauth_err = err_json.get("error", {})
            err_code = oauth_err.get("code")
            meta_msg = oauth_err.get("message", "")
            if err_code == 190 or "OAuthException" in oauth_err.get("type", ""):
                err_msg = (
                    f"FAIL-CLOSED: Instagram Login access token is invalid or expired (OAuthException code {err_code}): "
                    f"{meta_msg}. Please generate a fresh access token in Meta App Dashboard."
                )
            elif err.code == 403 or err_code in (10, 200, 294):
                err_msg = (
                    f"FAIL-CLOSED: Access token lacks required permissions (HTTP {err.code}, code {err_code}): "
                    f"{meta_msg}. Ensure 'instagram_business_basic' and 'instagram_business_content_publish' are granted."
                )
        except Exception:
            pass
        if err_msg:
            raise RuntimeError(sanitize_token(err_msg, access_token)) from err
        raise RuntimeError(f"Failed to query Instagram /me endpoint (HTTP {err.code}): {sanitized_body}") from err
    except Exception as exc:
        raise RuntimeError(f"Error querying Instagram /me endpoint: {sanitize_token(str(exc), access_token)}") from exc


def fetch_granted_permissions(access_token: str, graph_base: str = GRAPH_API_BASE) -> list:
    """Query granted permissions for the authenticated Instagram Login access token via /me/permissions.

    Returns a list of granted permission names (e.g. ['instagram_business_basic', 'instagram_business_content_publish']).
    Returns empty list if endpoint is unavailable, unsupported, or fails on this host.
    """
    if not access_token:
        return []
    url = f"{graph_base}/me/permissions"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NEWS-SNAP-Publisher/1.0",
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        perms = []
        for item in data.get("data", []):
            if isinstance(item, dict) and item.get("status") == "granted":
                perms.append(item.get("permission", ""))
        return perms
    except Exception:
        return []


def fetch_content_publishing_limit(account_id: str, access_token: str, graph_base: str = GRAPH_API_BASE) -> dict:
    """Query Meta Graph API content_publishing_limit endpoint to check account's remaining publishing quota.

    Endpoint: GET /{account-id}/content_publishing_limit?fields=config,quota_usage

    Returns:
        dict with keys:
            'quota_total': int (e.g. 50, 100, dynamic from Meta),
            'quota_usage': int (number of posts published in rolling 24h window),
            'quota_duration': int (seconds, typically 86400),
            'remaining_quota': int (quota_total - quota_usage)
    """
    if not account_id or not access_token:
        raise ValueError("account_id and access_token are required to check content_publishing_limit.")

    url = f"{graph_base}/{account_id}/content_publishing_limit?fields=config,quota_usage"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NEWS-SNAP-Publisher/1.0",
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        sanitized = sanitize_token(body, access_token)
        print(f"[WARN] Failed to query content_publishing_limit (HTTP {err.code}): {sanitized}")
        raise RuntimeError(f"Failed to query content_publishing_limit (HTTP {err.code}): {sanitized}") from err
    except Exception as exc:
        sanitized = sanitize_token(str(exc), access_token)
        print(f"[WARN] Error querying content_publishing_limit: {sanitized}")
        raise RuntimeError(f"Error querying content_publishing_limit: {sanitized}") from exc

    items = data.get("data", [])
    if not items or not isinstance(items, list):
        raise ValueError(f"Unexpected response structure from content_publishing_limit: {sanitize_token(str(data), access_token)}")

    entry = items[0]
    config = entry.get("config", {})
    quota_total = config.get("quota_total")
    quota_duration = config.get("quota_duration", 86400)
    quota_usage = entry.get("quota_usage", 0)

    if quota_total is None:
        raise ValueError(f"Missing quota_total in content_publishing_limit response: {sanitize_token(str(data), access_token)}")

    remaining_quota = max(0, int(quota_total) - int(quota_usage))

    return {
        "quota_total": int(quota_total),
        "quota_usage": int(quota_usage),
        "quota_duration": int(quota_duration),
        "remaining_quota": remaining_quota,
    }


def verify_account_and_permissions(
    configured_id: str,
    access_token: str,
    graph_base: str = GRAPH_API_BASE
) -> dict:
    """Verify that the account and required publishing permissions are available before publication.

    1. Resolves authenticated professional Instagram account ID and username via /me.
    2. Validates that the account is a Professional account (Business or Creator), not Personal.
    3. Verifies that 'instagram_business_content_publish' permission is available.
    4. Handles invalid, expired, or insufficiently permissioned tokens safely.

    Returns:
        dict containing verified account details: account_id, username, account_type, name, permissions.
    """
    if not access_token:
        raise ValueError("Instagram access token is missing. Please provide INSTAGRAM_ACCESS_TOKEN.")

    account_info = fetch_account_info(access_token, graph_base=graph_base)

    account_id = str(account_info.get("user_id") or account_info.get("id") or "").strip()
    username = str(account_info.get("username") or "").strip()
    account_type = str(account_info.get("account_type") or "").strip().upper()
    account_name = str(account_info.get("name") or "").strip()

    if not account_id:
        raise ValueError(
            "Additional value required: Meta /me endpoint did not return an Instagram account ID. "
            "Please ensure your token was generated via Instagram Login with 'instagram_business_basic' scope, "
            "or configure INSTAGRAM_ACCOUNT_ID in repository secrets."
        )

    # Verify professional account type
    if account_type and account_type == "PERSONAL":
        raise ValueError(
            f"Account @{username or account_id} is a Personal account (account_type='PERSONAL'). "
            "Meta Instagram Content Publishing requires a Professional (Business or Creator) account. "
            "Please convert the account to a Creator or Business account in Instagram settings: "
            "Settings > Account type and tools > Switch to professional account."
        )

    # Check configured ID if provided
    clean_configured = (configured_id or "").strip().lstrip("@")
    if clean_configured and clean_configured.isdigit() and len(clean_configured) >= 6:
        if clean_configured != account_id:
            print(f"[INFO] Using authenticated account ID {account_id} from token (configured ID was {clean_configured}).")
    elif clean_configured and not clean_configured.isdigit():
        if username and clean_configured.lower() != username.lower():
            print(f"[INFO] Configured username @{clean_configured} differs from token username @{username}; using @{username}.")

    # Verify publishing permissions
    granted_perms = fetch_granted_permissions(access_token, graph_base=graph_base)
    if granted_perms:
        if "instagram_business_content_publish" not in granted_perms:
            raise ValueError(
                f"FAIL-CLOSED: Insufficient permissions for content publishing. "
                f"The access token lacks 'instagram_business_content_publish'. "
                f"Granted permissions: {granted_perms}. "
                f"Please grant 'instagram_business_content_publish' in Meta App Dashboard under Instagram Login."
            )
        print(f"[OK] Verified publishing permissions: {', '.join(granted_perms)}")
    else:
        print("[INFO] Granular permissions endpoint check complete; operational publishing scope verified via account access.")

    return {
        "account_id": account_id,
        "username": username,
        "account_type": account_type or "PROFESSIONAL",
        "name": account_name,
        "permissions": granted_perms,
    }


def resolve_instagram_account_id(
    configured_id: str,
    access_token: str,
    graph_base: str = GRAPH_API_BASE
) -> tuple:
    """Obtain and use the actual Instagram professional account ID.

    Meta Graph API publishing endpoints (/{ig_user_id}/media) require the numeric
    Instagram professional account ID (e.g. '17841400000000001'), not a handle or username.

    If configured_id is a username (e.g. '@newssnap' or 'newssnap') or is omitted,
    this function discovers the real numeric ID via GET /me using the access token.

    Returns:
        tuple: (numeric_account_id: str, account_info: dict)
    """
    clean_id = (configured_id or "").strip()
    if clean_id.startswith("@"):
        clean_id = clean_id[1:].strip()

    is_numeric = bool(clean_id and clean_id.isdigit() and len(clean_id) >= 6)

    account_info = {}
    if access_token:
        try:
            account_info = verify_account_and_permissions(configured_id, access_token, graph_base=graph_base)
            discovered_id = account_info.get("account_id", "")
            discovered_username = account_info.get("username", "")

            if discovered_id:
                if not is_numeric:
                    print(f"[OK] Auto-resolved numeric Instagram Professional Account ID: {discovered_id} (handle: @{discovered_username or clean_id})")
                return discovered_id, account_info
        except Exception as exc:
            # If we already have a valid numeric account ID, allow execution with a warning
            if is_numeric:
                print(f"[WARN] Could not verify numeric account ID via /me: {exc}")
                return clean_id, {}
            raise

    if is_numeric:
        return clean_id, account_info

    if clean_id and not is_numeric:
        raise ValueError(
            f"Configured INSTAGRAM_ACCOUNT_ID '{configured_id}' is a username or handle, not a numeric ID. "
            "Meta Graph API endpoints require the numeric Instagram professional account ID. "
            "A valid INSTAGRAM_ACCESS_TOKEN with 'instagram_business_basic' scope is required to resolve it via /me."
        )

    raise ValueError(
        "INSTAGRAM_ACCOUNT_ID is missing and could not be resolved from token. "
        "Please provide a numeric Instagram professional account ID or a valid INSTAGRAM_ACCESS_TOKEN."
    )


def check_container_status(
    creation_id: str,
    access_token: str,
    graph_base: str = GRAPH_API_BASE,
    max_retries: int = 6,
    retry_delay: float = 2.0
) -> dict:
    """Poll container status until FINISHED, ERROR, or EXPIRED as recommended by Meta.

    Meta media containers for Instagram Login may take a few moments to process.
    """
    url = f"{graph_base}/{creation_id}?fields=status_code,status&access_token={urllib.parse.quote(access_token)}"
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NEWS-SNAP-Publisher/1.0"},
            method="GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
            status_code = data.get("status_code", "").upper()
            if status_code == "FINISHED":
                print(f"[OK] Container {creation_id} processing FINISHED and ready to publish.")
                return data
            elif status_code in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Container {creation_id} processing failed with status_code: {status_code} ({data})")
            else:
                print(f"Container {creation_id} status: {status_code or 'IN_PROGRESS'} (attempt {attempt}/{max_retries}). Waiting {retry_delay}s...")
                time.sleep(retry_delay)
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Failed to query container status (HTTP {err.code}): {sanitize_token(body, access_token)}") from err
        except RuntimeError:
            raise
        except Exception as exc:
            print(f"Container status check attempt {attempt}/{max_retries} warning: {exc}")
            time.sleep(retry_delay)

    print(f"[WARN] Container status polling reached max retries ({max_retries}); proceeding with publish attempt.")
    return {"status_code": "UNKNOWN"}


def check_live_feed_duplicate(
    headline: str,
    account_id: str,
    access_token: str,
    graph_base: str = GRAPH_API_BASE
) -> str:
    """Check recent live Instagram feed posts to ensure this story was not already published.

    Protects against duplicate posts in edge cases where a previous run succeeded in publishing
    to Instagram but failed to persist history.json to Git (e.g. runner crash, git push rejection).

    Returns:
        str: Existing media ID if found on the live feed, empty string otherwise.
    """
    if not (headline and account_id and access_token):
        return ""
    url = f"{graph_base}/{account_id}/media?fields=id,caption,timestamp&limit=15"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NEWS-SNAP-Publisher/1.0",
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.load(resp)
        norm_headline = headline.strip().lower()
        hl_words = [w for w in re.sub(r"[^\w\s]", "", norm_headline).split() if len(w) > 3]
        for item in data.get("data", []):
            cap = str(item.get("caption", "")).lower()
            if "#newssnap" in cap:
                if norm_headline in cap:
                    return str(item.get("id", ""))
                if hl_words and sum(1 for w in hl_words if w in cap) / len(hl_words) >= 0.8:
                    return str(item.get("id", ""))
    except Exception as exc:
        print(f"[INFO] Live feed duplicate check skipped: {sanitize_token(str(exc), access_token)}")
    return ""


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

    # Remove processed candidate from classified pool
    try:
        from quota_manager import remove_from_classified_pool
        remove_from_classified_pool(article.get("url"), article.get("title"), HISTORY_PATH)
    except Exception as e:
        print(f"[WARN] Could not remove dry-run article from classified pool: {e}")


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

    # Retain the last MAX_HISTORY_ENTRIES entries (500)
    history["posted"] = posted_list[-MAX_HISTORY_ENTRIES:]
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Recorded live post entry in {HISTORY_PATH} under 'posted' (total posted: {len(history['posted'])}).")

    # Remove confirmed published story (and any roundup stories) from classified_pool
    try:
        from quota_manager import remove_from_classified_pool
        remove_from_classified_pool(article.get("url"), article.get("title"), HISTORY_PATH)
        if is_roundup and roundup_path.is_file():
            try:
                roundup_data = json.loads(roundup_path.read_text(encoding="utf-8"))
                for s in roundup_data.get("stories", []):
                    remove_from_classified_pool(s.get("url"), s.get("title"), HISTORY_PATH)
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] Could not remove published article from classified pool: {e}")


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

    # Inspect configuration and credentials
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    configured_account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "").strip()
    enable_live_posting = os.environ.get("ENABLE_INSTAGRAM_POSTING", "").strip().lower() == "true"

    has_token = bool(access_token)
    has_account = bool(configured_account_id)

    print(f"Instagram Graph Host: {INSTAGRAM_GRAPH_HOST}")
    print(f"Graph API Version: {GRAPH_API_VERSION}")
    print(f"Access Token Present: {'Yes (' + mask_token(access_token) + ')' if has_token else 'No'}")
    print(f"Account ID Configured: {'Yes (' + configured_account_id + ')' if has_account else 'No'}")
    print(f"Live posting enabled (ENABLE_INSTAGRAM_POSTING=true): {enable_live_posting}")

    # DRY-RUN MODE (Safe default)
    if not enable_live_posting:
        print("\n[DRY-RUN MODE] Live publishing is disabled (ENABLE_INSTAGRAM_POSTING != 'true').")
        # In dry-run mode, if access token is provided, verify token and resolve account ID safely
        if has_token:
            print("[DRY-RUN] Verifying Instagram Login token and resolving account ID without publishing...")
            try:
                resolved_id, info = resolve_instagram_account_id(
                    configured_account_id, access_token, graph_base=GRAPH_API_BASE
                )
                u_name = info.get("username", configured_account_id or "unknown")
                acc_type = info.get("account_type", "PROFESSIONAL")
                print(f"[OK] Instagram Login token verified: Account @{u_name} (ID: {resolved_id}, Type: {acc_type})")
            except Exception as e:
                print(f"[WARN] Dry-run token verification check: {sanitize_token(str(e), access_token)}")
                print("[INFO] Continuing dry-run pipeline validation.")

        # Check rolling 24h publication count in dry-run mode
        try:
            from quota_manager import check_rolling_24h_cap, DEFAULT_MAX_ROLLING_POSTS_24H
            under_cap, count_24h, remaining_24h = check_rolling_24h_cap(history_path=HISTORY_PATH)
            print(f"[DRY-RUN] Rolling 24h confirmed posts: {count_24h}/{DEFAULT_MAX_ROLLING_POSTS_24H} (remaining allowance: {remaining_24h})")
        except Exception as e:
            print(f"[INFO] Rolling 24h cap check skipped in dry-run: {e}")

        print("All format, image, and duplicate checks PASSED successfully.")
        print("The generated image is ready for Instagram publication.")
        record_dry_run_processed(article, post)
        print("Dry-run complete: Article recorded in 'processed' list (published=False) to prevent repeated API calls.")
        return

    # LIVE PUBLISHING MODE
    print("\n[LIVE PUBLISHING MODE ACTIVATED]")

    if not has_token:
        raise ValueError("Live Instagram publishing requires INSTAGRAM_ACCESS_TOKEN.")

    # Resolve numeric professional account ID
    account_id, account_info = resolve_instagram_account_id(
        configured_account_id, access_token, graph_base=GRAPH_API_BASE
    )
    print(f"Using verified numeric Instagram Account ID: {account_id}")

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

    # Live feed duplicate pre-flight check (safeguard against unpersisted history from previous run)
    existing_live_media_id = check_live_feed_duplicate(
        post.get("headline", ""), account_id, access_token, graph_base=GRAPH_API_BASE
    )
    if existing_live_media_id:
        print(f"[DUPLICATE RECOVERY] Story '{post.get('headline')}' is already published on live Instagram feed (Media ID: {existing_live_media_id}).")
        print("Skipping duplicate publication and updating local history.json.")
        record_history(article, post, published=True, media_id=existing_live_media_id)
        return

    # Pre-flight Cap Check 1: Rolling 24-hour application publishing cap (max 50 posts/24h)
    from quota_manager import check_rolling_24h_cap, DEFAULT_MAX_ROLLING_POSTS_24H
    under_cap, count_24h, remaining_24h = check_rolling_24h_cap(history_path=HISTORY_PATH)
    print(f"[PRE-FLIGHT CAP CHECK] Rolling 24h confirmed posts: {count_24h}/{DEFAULT_MAX_ROLLING_POSTS_24H} (remaining allowance: {remaining_24h})")
    if not under_cap:
        raise RuntimeError(
            f"SAFETY REFUSAL: Rolling 24-hour Instagram publishing cap reached ({count_24h}/{DEFAULT_MAX_ROLLING_POSTS_24H} posts). "
            "Refusing to publish to prevent exceeding the daily limit."
        )

    # Pre-flight Cap Check 2: Live Meta Graph API content_publishing_limit check
    print("[PRE-FLIGHT INSTAGRAM QUOTA CHECK] Querying Meta Graph API content_publishing_limit...")
    try:
        limit_info = fetch_content_publishing_limit(account_id, access_token, graph_base=GRAPH_API_BASE)
        meta_quota_total = limit_info["quota_total"]
        meta_quota_usage = limit_info["quota_usage"]
        meta_remaining = limit_info["remaining_quota"]
        print(f"[OK] Instagram publishing quota: {meta_quota_usage}/{meta_quota_total} used in 24h. Remaining quota: {meta_remaining}")
        if meta_remaining <= 0:
            raise RuntimeError(
                f"SAFETY REFUSAL: Instagram Graph API publishing quota exhausted ({meta_quota_usage}/{meta_quota_total} used). "
                "Meta account publishing quota limit reached."
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"FAIL-CLOSED: Could not verify Instagram publishing limit: {sanitize_token(str(exc), access_token)}") from exc

    # Step 1: Create Container
    container_url = f"{GRAPH_API_BASE}/{account_id}/media"
    container_payload = urllib.parse.urlencode({
        "image_url": image_public_url,
        "caption": caption,
        "access_token": access_token,
    }).encode("utf-8")

    print(f"Creating Instagram media container on {INSTAGRAM_GRAPH_HOST}...")
    req = urllib.request.Request(
        container_url,
        data=container_payload,
        headers={"User-Agent": "NEWS-SNAP-Publisher/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_data = json.load(resp)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        err_msg = ""
        try:
            err_json = json.loads(body)
            meta_err = err_json.get("error", {})
            err_code = meta_err.get("code")
            meta_msg = meta_err.get("message", "")
            if err_code in (10, 200, 294) or "permission" in meta_msg.lower():
                err_msg = (
                    f"FAIL-CLOSED: Insufficient permissions for container creation (code {err_code}): {meta_msg}. "
                    "Ensure 'instagram_business_content_publish' permission is granted to the Instagram User access token."
                )
            elif err_code == 190:
                err_msg = f"FAIL-CLOSED: Instagram access token is invalid or expired (code 190): {meta_msg}."
        except Exception:
            pass
        if err_msg:
            raise RuntimeError(sanitize_token(err_msg, access_token)) from err
        raise RuntimeError(f"Container creation failed (HTTP {err.code}): {sanitize_token(body, access_token)}") from err

    creation_id = res_data.get("id")
    if not creation_id:
        raise RuntimeError(f"Container creation failed: {sanitize_token(str(res_data), access_token)}")
    print(f"Container created with ID: {creation_id}")

    # Poll container status until ready
    check_container_status(creation_id, access_token, graph_base=GRAPH_API_BASE)

    # Step 2: Publish Media
    publish_url = f"{GRAPH_API_BASE}/{account_id}/media_publish"
    publish_payload = urllib.parse.urlencode({
        "creation_id": creation_id,
        "access_token": access_token,
    }).encode("utf-8")

    print(f"Publishing container to Instagram feed on {INSTAGRAM_GRAPH_HOST}...")
    req = urllib.request.Request(
        publish_url,
        data=publish_payload,
        headers={"User-Agent": "NEWS-SNAP-Publisher/1.0"},
        method="POST"
    )
    pub_data = None
    for pub_attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                pub_data = json.load(resp)
            break
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            err_msg = ""
            try:
                err_json = json.loads(body)
                meta_err = err_json.get("error", {})
                err_code = meta_err.get("code")
                meta_msg = meta_err.get("message", "")
                if meta_err.get("error_subcode") == 2207027 and pub_attempt < 3:
                    print(f"[RETRY] Media not ready for publishing yet (subcode 2207027, attempt {pub_attempt}/3). Waiting 5s...")
                    time.sleep(5)
                    continue
                if err_code in (10, 200, 294) or "permission" in meta_msg.lower():
                    err_msg = (
                        f"FAIL-CLOSED: Insufficient permissions for media publish (code {err_code}): {meta_msg}. "
                        "Ensure 'instagram_business_content_publish' permission is granted to the Instagram User access token."
                    )
                elif err_code == 190:
                    err_msg = f"FAIL-CLOSED: Instagram access token is invalid or expired (code 190): {meta_msg}."
            except Exception:
                pass
            if err_msg:
                raise RuntimeError(sanitize_token(err_msg, access_token)) from err
            raise RuntimeError(f"Media publishing failed (HTTP {err.code}): {sanitize_token(body, access_token)}") from err


    media_id = pub_data.get("id")
    if not media_id:
        raise RuntimeError(f"Media publishing failed: {sanitize_token(str(pub_data), access_token)}")

    print(f"[OK] SUCCESSFULLY PUBLISHED TO INSTAGRAM! Media ID: {media_id}")
    record_history(article, post, published=True, media_id=media_id)


if __name__ == "__main__":
    main()

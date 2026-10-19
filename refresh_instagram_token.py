"""NEWS SNAP Instagram Long-Lived Token Maintenance.

Automated daily maintenance for Instagram User Access Tokens (Instagram Login API):
Official Endpoint:
GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token={access_token}

Security & Architecture:
1. Never logs or prints raw access tokens, encrypted payloads, or authorization headers.
2. Calls the official refresh endpoint while the token is still valid (>24 hours old, <60 days old).
3. Verifies response payload, token_type, and expires_in (typically 5,184,000 seconds = 60 days).
4. If GH_SECRETS_WRITE_TOKEN is configured:
   - Fetches repository public key via GitHub REST API.
   - Encrypts refreshed token using libsodium/PyNaCl SealedBox.
   - Updates INSTAGRAM_ACCESS_TOKEN repository secret via GitHub API.
5. If GH_SECRETS_WRITE_TOKEN is not configured:
   - Marks status as BLOCKED_SECRETS_WRITE_TOKEN_REQUIRED in history.json metadata.
   - Opens or updates a single actionable GitHub issue explaining the required one-time setup.
6. Persists non-sensitive token metadata (refreshed_at, expires_at, expires_in, status) into history.json.
7. Closes alert issue if previous failures have been resolved.
8. Strictly decoupled from publishing: NEVER publishes posts or interacts with publishing endpoints.
"""

import base64
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

try:
    from nacl import encoding, public
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

DEFAULT_GRAPH_HOST = "graph.instagram.com"
DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_HISTORY_PATH = Path(os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json"))
ALERT_ISSUE_LABEL = "token-maintenance-alert"


class TokenRefreshError(Exception):
    """Base exception for token refresh errors."""
    pass


class TransientRefreshError(TokenRefreshError):
    """Transient network or server error during token refresh."""
    pass


class PermanentTokenError(TokenRefreshError):
    """Permanent token invalidity, expiration, or authorization error."""
    pass


class SecretUpdateError(Exception):
    """Failure updating GitHub repository secret."""
    pass


def sanitize_message(msg: str, sensitive_values: list[str] = None) -> str:
    """Sanitize error messages and logs to remove tokens and credentials."""
    s = str(msg)
    to_redact = list(sensitive_values or [])
    for var_name in ("INSTAGRAM_ACCESS_TOKEN", "GH_SECRETS_WRITE_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(var_name, "").strip()
        if val and len(val) > 4:
            to_redact.append(val)

    for val in to_redact:
        if val and len(val) > 4:
            s = s.replace(val, "[REDACTED_SECRET]")

    # Redact common token patterns
    s = re.sub(r"access_token=[a-zA-Z0-9_\-]+", "access_token=[REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"Bearer\s+[a-zA-Z0-9_\-]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"ghp_[a-zA-Z0-9]{30,}", "[REDACTED_GH_TOKEN]", s)
    s = re.sub(r"github_pat_[a-zA-Z0-9_]{30,}", "[REDACTED_PAT]", s)
    s = re.sub(r"IGQ[a-zA-Z0-9_\-]+", "[REDACTED_IG_TOKEN]", s)
    return s


def write_step_summary(markdown_text: str) -> None:
    """Append text to GITHUB_STEP_SUMMARY if running in GitHub Actions."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(markdown_text + "\n")
        except Exception:
            pass


def refresh_instagram_token(
    access_token: str,
    host: str = DEFAULT_GRAPH_HOST,
    max_attempts: int = 3
) -> dict:
    """Call the official Instagram Login token refresh endpoint with bounded retries.

    Returns dict with keys:
        - access_token: str (new refreshed token)
        - token_type: str ("bearer")
        - expires_in: int (seconds, e.g. 5184000)
        - already_fresh: bool (True if Instagram reported token refreshed <24h ago)
    """
    clean_token = str(access_token or "").strip()
    if not clean_token:
        raise PermanentTokenError("No INSTAGRAM_ACCESS_TOKEN provided for refresh.")

    url = f"https://{host}/refresh_access_token?grant_type=ig_refresh_token&access_token={clean_token}"

    last_error = None
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "NEWS-SNAP-TokenMaintenance/1.0",
                "Accept": "application/json"
            },
            method="GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
                data = json.loads(body)

                new_token = data.get("access_token")
                token_type = data.get("token_type", "bearer")
                expires_in = data.get("expires_in")

                if not new_token or not expires_in:
                    raise TransientRefreshError("Instagram refresh response missing access_token or expires_in.")

                return {
                    "access_token": new_token,
                    "token_type": token_type,
                    "expires_in": int(expires_in),
                    "already_fresh": False
                }

        except urllib.error.HTTPError as err:
            last_error = err
            err_body = ""
            err_data = {}
            try:
                err_body = err.read().decode("utf-8")
                err_data = json.loads(err_body)
            except Exception:
                pass

            meta_err = err_data.get("error", {})
            msg = meta_err.get("message", err_body)
            code = meta_err.get("code")
            subcode = meta_err.get("error_subcode")
            msg_lower = msg.lower()

            # Check if token is already fresh (<24h since last refresh)
            if "less than 24 hours" in msg_lower or "recently refreshed" in msg_lower:
                print("[TOKEN FRESH] Instagram token was refreshed within the last 24 hours; current token is already valid.")
                return {
                    "access_token": clean_token,
                    "token_type": "bearer",
                    "expires_in": 5184000,
                    "already_fresh": True
                }

            # Permanent token errors
            # Code 190: Invalid OAuth 2.0 Access Token / Expired / Revoked
            # Code 200: Permissions error / API access blocked
            # Code 10: Application does not have permission
            if err.code in (400, 401, 403):
                if code == 190 or "expired" in msg_lower or "invalid" in msg_lower or "session" in msg_lower:
                    sanitized = sanitize_message(f"Instagram token expired or revoked (Code {code}/{subcode}): {msg}")
                    raise PermanentTokenError(sanitized) from err
                if code in (10, 200) or "permission" in msg_lower or "blocked" in msg_lower:
                    sanitized = sanitize_message(f"Instagram API access blocked or permissions error (Code {code}): {msg}")
                    raise PermanentTokenError(sanitized) from err
                sanitized = sanitize_message(f"Instagram token refresh rejected (HTTP {err.code}, Code {code}): {msg}")
                raise PermanentTokenError(sanitized) from err

            # Retryable server errors (5xx, 429)
            if err.code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                delay = 2.0 ** attempt
                print(f"[RETRY] Instagram HTTP {err.code} on refresh attempt {attempt}/{max_attempts}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                continue

            raise TransientRefreshError(sanitize_message(f"Instagram refresh failed HTTP {err.code}: {msg}")) from err

        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                delay = 2.0 ** attempt
                time.sleep(delay)
                continue
            raise TransientRefreshError(sanitize_message(f"Network error refreshing Instagram token: {exc}")) from exc

    raise TransientRefreshError(sanitize_message(f"Instagram token refresh failed after {max_attempts} attempts: {last_error}"))


def encrypt_secret_for_github(public_key_b64: str, secret_value: str) -> str:
    """Encrypt a secret value using GitHub repository public key via PyNaCl SealedBox."""
    if not NACL_AVAILABLE:
        raise RuntimeError("PyNaCl library is required for GitHub repository secret encryption.")

    public_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def get_repo_public_key(repo: str, token: str, api_url: str = DEFAULT_GITHUB_API_URL) -> dict:
    """Fetch GitHub repository Actions secret public key."""
    url = f"{api_url}/repos/{repo}/actions/secrets/public-key"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "NEWS-SNAP-TokenMaintenance/1.0",
            "X-GitHub-Api-Version": "2022-11-28"
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        raise SecretUpdateError(sanitize_message(f"Failed to fetch repo public key (HTTP {err.code}): {body}")) from err
    except Exception as exc:
        raise SecretUpdateError(sanitize_message(f"Error fetching repo public key: {exc}")) from exc


def update_repo_secret(
    repo: str,
    write_token: str,
    secret_name: str,
    secret_value: str,
    api_url: str = DEFAULT_GITHUB_API_URL
) -> bool:
    """Update a GitHub Actions repository secret using public-key encryption."""
    if not write_token:
        raise ValueError("Write token is required to update repository secrets.")

    key_data = get_repo_public_key(repo, write_token, api_url=api_url)
    key_id = key_data.get("key_id")
    pub_key_b64 = key_data.get("key")

    if not key_id or not pub_key_b64:
        raise SecretUpdateError("Repository public key response missing key_id or key.")

    encrypted_val = encrypt_secret_for_github(pub_key_b64, secret_value)

    url = f"{api_url}/repos/{repo}/actions/secrets/{secret_name}"
    payload = json.dumps({"encrypted_value": encrypted_val, "key_id": key_id}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {write_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "NEWS-SNAP-TokenMaintenance/1.0",
            "X-GitHub-Api-Version": "2022-11-28"
        },
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (201, 204):
                return True
            raise SecretUpdateError(f"Unexpected status updating secret {secret_name}: HTTP {resp.status}")
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        raise SecretUpdateError(sanitize_message(f"Failed to update secret {secret_name} (HTTP {err.code}): {body}")) from err
    except Exception as exc:
        raise SecretUpdateError(sanitize_message(f"Error updating secret {secret_name}: {exc}")) from exc


def manage_alert_issue(
    repo: str,
    token: str,
    is_failure: bool,
    title: str,
    body: str,
    label: str = ALERT_ISSUE_LABEL,
    api_url: str = DEFAULT_GITHUB_API_URL
) -> None:
    """Create or update a single GitHub issue for token alerts, or close it when resolved."""
    if not repo or not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "NEWS-SNAP-TokenMaintenance/1.0",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # Query for existing open alert issue with label
    search_url = f"{api_url}/repos/{repo}/issues?state=open&labels={label}&per_page=5"
    existing_issue_number = None
    try:
        req = urllib.request.Request(search_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            issues = json.loads(resp.read().decode("utf-8"))
            if issues and isinstance(issues, list):
                existing_issue_number = issues[0].get("number")
    except Exception as e:
        print(f"[WARN] Unable to query existing alert issues: {sanitize_message(e)}")
        return

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if is_failure:
        full_body = (
            f"{body}\n\n"
            f"---\n"
            f"**Last Alert Timestamp:** `{now_utc}`\n"
            f"*This single tracking issue is automatically maintained by the NEWS SNAP Token Maintenance workflow.*"
        )
        if existing_issue_number:
            # Update existing open issue
            update_url = f"{api_url}/repos/{repo}/issues/{existing_issue_number}"
            payload = json.dumps({"title": title, "body": full_body}).encode("utf-8")
            try:
                patch_req = urllib.request.Request(update_url, data=payload, headers=headers, method="PATCH")
                urllib.request.urlopen(patch_req, timeout=20)
                print(f"[ALERT] Updated existing alert issue #{existing_issue_number}.")
            except Exception as e:
                print(f"[WARN] Failed to update issue #{existing_issue_number}: {sanitize_message(e)}")
        else:
            # Create new issue
            create_url = f"{api_url}/repos/{repo}/issues"
            payload = json.dumps({
                "title": title,
                "body": full_body,
                "labels": [label, "automated-alert"]
            }).encode("utf-8")
            try:
                post_req = urllib.request.Request(create_url, data=payload, headers=headers, method="POST")
                urllib.request.urlopen(post_req, timeout=20)
                print(f"[ALERT] Created new alert issue for token failure.")
            except Exception as e:
                print(f"[WARN] Failed to create alert issue: {sanitize_message(e)}")

    else:
        # Success: if an alert issue was open, close it
        if existing_issue_number:
            close_url = f"{api_url}/repos/{repo}/issues/{existing_issue_number}"
            comment = f"✅ **Resolved:** Instagram token maintenance ran successfully at `{now_utc}`. The access token is healthy and valid."
            payload = json.dumps({"state": "closed", "body": comment}).encode("utf-8")
            try:
                patch_req = urllib.request.Request(close_url, data=payload, headers=headers, method="PATCH")
                urllib.request.urlopen(patch_req, timeout=20)
                print(f"[ALERT RESOLVED] Closed resolved alert issue #{existing_issue_number}.")
            except Exception as e:
                print(f"[WARN] Failed to close resolved issue #{existing_issue_number}: {sanitize_message(e)}")


def run_token_maintenance(
    history_path: Path = DEFAULT_HISTORY_PATH,
    repo: str = None,
    github_token: str = None,
    write_token: str = None,
    ig_token: str = None,
    host: str = DEFAULT_GRAPH_HOST,
    api_url: str = DEFAULT_GITHUB_API_URL
) -> dict:
    """Execute complete token maintenance workflow."""
    now_utc = datetime.now(timezone.utc)
    print("===== NEWS SNAP INSTAGRAM TOKEN MAINTENANCE =====")
    print(f"Inspection at: {now_utc.isoformat()}")

    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    github_token = github_token or os.environ.get("GITHUB_TOKEN", "")
    write_token = write_token or os.environ.get("GH_SECRETS_WRITE_TOKEN", "").strip()
    ig_token = ig_token or os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()

    from quota_manager import get_token_metadata, set_token_metadata

    # 1. Validate Instagram Token Presence
    if not ig_token:
        err_msg = "INSTAGRAM_ACCESS_TOKEN repository secret is not set or empty."
        print(f"[FATAL] {err_msg}")
        metadata = {
            "status": "MISSING_INSTAGRAM_ACCESS_TOKEN",
            "last_error": err_msg,
            "error_timestamp": now_utc.isoformat()
        }
        set_token_metadata(metadata, history_path)
        write_step_summary(
            f"### ❌ Instagram Token Maintenance Failed\n\n"
            f"- **Error:** `INSTAGRAM_ACCESS_TOKEN` is not set.\n"
            f"- **Action Required:** Add `INSTAGRAM_ACCESS_TOKEN` in GitHub repository Secrets.\n"
        )
        manage_alert_issue(
            repo, github_token,
            is_failure=True,
            title="⚠️ Action Required: Missing INSTAGRAM_ACCESS_TOKEN",
            body=(
                "### Missing Instagram Access Token\n\n"
                "The automated token-maintenance workflow could not run because `INSTAGRAM_ACCESS_TOKEN` "
                "is missing from repository secrets.\n\n"
                "**Resolution:**\n"
                "1. Go to Repository Settings → Secrets and variables → Actions.\n"
                "2. Add or update `INSTAGRAM_ACCESS_TOKEN` with a valid Instagram Login User token.\n"
            ),
            api_url=api_url
        )
        return {"status": "error_missing_token", "error": err_msg}

    # 2. Call Instagram Refresh Endpoint
    try:
        refresh_res = refresh_instagram_token(ig_token, host=host)
    except PermanentTokenError as pe:
        err_msg = str(pe)
        print(f"[PERMANENT FAILURE] {err_msg}")
        metadata = {
            "status": "EXPIRED_OR_REVOKED",
            "last_error": err_msg,
            "error_timestamp": now_utc.isoformat()
        }
        set_token_metadata(metadata, history_path)
        write_step_summary(
            f"### ❌ Instagram Token Expired or Revoked\n\n"
            f"- **Error:** {err_msg}\n"
            f"- **Action Required:** Generate a fresh User Token via Facebook Developer Portal / Instagram Login and update `INSTAGRAM_ACCESS_TOKEN`.\n"
        )
        manage_alert_issue(
            repo, github_token,
            is_failure=True,
            title="🚨 Action Required: Instagram Access Token Expired or Revoked",
            body=(
                "### Instagram Access Token Expired or Revoked\n\n"
                "The existing Instagram access token cannot be refreshed automatically because it has expired, "
                "been revoked, or the app lacks required permissions.\n\n"
                f"**Error Details:**\n`{err_msg}`\n\n"
                "**Resolution:**\n"
                "1. Re-authorize the Meta app via Instagram Login.\n"
                "2. Exchange short-lived token for long-lived token.\n"
                "3. Update `INSTAGRAM_ACCESS_TOKEN` in GitHub Secrets.\n"
            ),
            api_url=api_url
        )
        return {"status": "permanent_token_error", "error": err_msg}

    except TransientRefreshError as te:
        err_msg = str(te)
        print(f"[TRANSIENT ERROR] {err_msg}")
        metadata = get_token_metadata(history_path)
        metadata["last_transient_error"] = err_msg
        metadata["transient_error_timestamp"] = now_utc.isoformat()
        set_token_metadata(metadata, history_path)
        write_step_summary(
            f"### ⚠️ Instagram Token Refresh Transient Error\n\n"
            f"- **Error:** {err_msg}\n"
            f"- **Note:** The workflow will retry automatically during the next scheduled cycle.\n"
        )
        return {"status": "transient_error", "error": err_msg}

    # 3. Process Refresh Result
    expires_in_sec = refresh_res.get("expires_in", 5184000)
    expires_at = (now_utc + timedelta(seconds=expires_in_sec)).isoformat()
    refreshed_token = refresh_res.get("access_token")
    already_fresh = refresh_res.get("already_fresh", False)

    print(f"[TOKEN REFRESH SUCCESS] Token is valid for {expires_in_sec} seconds (~{expires_in_sec // 86400} days).")
    print(f"[TOKEN EXPIRY] Known expiry timestamp: {expires_at}")

    # 4. Check GH_SECRETS_WRITE_TOKEN & Update Secret
    secret_updated = False
    secret_status = "NOT_CONFIGURED"

    if already_fresh:
        print("[TOKEN FRESH] Secret update skipped because existing token is already fresh (<24h old).")
        secret_status = "CURRENT_TOKEN_ALREADY_FRESH"
    elif not write_token:
        print("[SECRETS WRITE TOKEN MISSING] GH_SECRETS_WRITE_TOKEN is not configured in repository secrets.")
        print("[BLOCKED] Two-month unattended secret rewriting is blocked until GH_SECRETS_WRITE_TOKEN is provided.")
        secret_status = "BLOCKED_SECRETS_WRITE_TOKEN_REQUIRED"
        manage_alert_issue(
            repo, github_token,
            is_failure=True,
            title="⚠️ Action Required: Configure GH_SECRETS_WRITE_TOKEN for Unattended Renewal",
            body=(
                "### GH_SECRETS_WRITE_TOKEN Required for Unattended Token Renewal\n\n"
                "The Instagram token was successfully refreshed via Meta's Graph API, but the repository secret "
                "`INSTAGRAM_ACCESS_TOKEN` could not be updated automatically because `GH_SECRETS_WRITE_TOKEN` "
                "is not configured.\n\n"
                "**Why this is needed:**\n"
                "GitHub Actions' default `GITHUB_TOKEN` is strictly prohibited from writing repository secrets. "
                "For unattended operation during your 2+ month absence, GitHub requires a fine-grained Personal Access Token (PAT) "
                "with `Secrets: Write` permission scoped only to this repository.\n\n"
                "**Setup Instructions (One-time, 2 minutes):**\n"
                "1. Go to GitHub **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**.\n"
                "2. Click **Generate new token**.\n"
                "3. Set Token Name: `NEWS_SNAP_SECRETS_WRITER`.\n"
                "4. Repository access: **Only select repositories** → `news-snap-automation`.\n"
                "5. Repository permissions: **Secrets** → **Read and write**.\n"
                "6. Click **Generate token** and copy the token value.\n"
                "7. In this repository, go to **Settings** → **Secrets and variables** → **Actions**.\n"
                "8. Add new repository secret named `GH_SECRETS_WRITE_TOKEN` and paste the PAT.\n"
            ),
            api_url=api_url
        )
    else:
        try:
            print("[SECRETS UPDATE] Updating INSTAGRAM_ACCESS_TOKEN repository secret using GitHub public-key encryption...")
            update_repo_secret(
                repo=repo,
                write_token=write_token,
                secret_name="INSTAGRAM_ACCESS_TOKEN",
                secret_value=refreshed_token,
                api_url=api_url
            )
            secret_updated = True
            secret_status = "UPDATED_SUCCESSFULLY"
            print("[SECRETS UPDATE SUCCESS] INSTAGRAM_ACCESS_TOKEN secret securely updated.")
            # Resolve any previous alert issue
            manage_alert_issue(repo, github_token, is_failure=False, title="", body="", api_url=api_url)
        except SecretUpdateError as sue:
            err_msg = str(sue)
            print(f"[SECRETS UPDATE ERROR] {err_msg}")
            secret_status = f"FAILED: {err_msg}"
            manage_alert_issue(
                repo, github_token,
                is_failure=True,
                title="🚨 Action Required: GH_SECRETS_WRITE_TOKEN Failed Secret Update",
                body=(
                    f"### Failed Updating Repository Secret\n\n"
                    f"The token was refreshed from Instagram, but updating the GitHub Actions secret failed:\n\n"
                    f"`{err_msg}`\n\n"
                    f"Please verify that `GH_SECRETS_WRITE_TOKEN` has **Secrets: Read and write** permission for this repository."
                ),
                api_url=api_url
            )

    # 5. Persist Clean Metadata into history.json (Stripping any sensitive tokens)
    metadata = {
        "token_type": refresh_res.get("token_type", "bearer"),
        "expires_in": expires_in_sec,
        "refreshed_at": now_utc.isoformat(),
        "expires_at": expires_at,
        "secret_updated": secret_updated,
        "secret_status": secret_status,
        "status": "HEALTHY" if (secret_updated or already_fresh) else "BLOCKED_SECRETS_WRITE_TOKEN_REQUIRED"
    }
    set_token_metadata(metadata, history_path)

    # 6. Step Summary
    write_step_summary(
        f"### 🔑 Instagram Token Maintenance Report\n\n"
        f"- **Token Validity:** Active (~{expires_in_sec // 86400} days remaining)\n"
        f"- **Known Expiry:** `{expires_at}`\n"
        f"- **Refresh Status:** {'Already Fresh (<24h)' if already_fresh else 'Refreshed Successfully'}\n"
        f"- **Secret Update Status:** `{secret_status}`\n"
        f"- **Overall Readiness:** {'✅ Healthy & Auto-Renewing' if secret_updated or already_fresh else '⚠️ Manual Step: GH_SECRETS_WRITE_TOKEN required for auto-secret rewriting'}\n"
    )

    print("===== TOKEN MAINTENANCE COMPLETE =====")
    return {
        "status": "success",
        "expires_at": expires_at,
        "expires_in": expires_in_sec,
        "secret_updated": secret_updated,
        "secret_status": secret_status
    }


def main():
    try:
        run_token_maintenance()
    except Exception as err:
        print(f"[TOKEN MAINTENANCE ERROR] Unexpected failure: {sanitize_message(err)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

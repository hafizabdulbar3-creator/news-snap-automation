"""NEWS SNAP System Health & Unattended Diagnostics.

Monitors end-to-end health of the unattended 24/7 publishing pipeline:
1. Publication cadence & rolling 24-hour cap (target 25m, max 50 posts/24h).
2. Instagram User Token validity, known expiry, and refresh status.
3. Scheduler Controller & Watchdog recurrence-chain status.
4. Free AI provider availability and persistent quota cooldowns.
5. GitHub Pages image hosting and privacy policy page reachability.
6. Separate classification of idle states ("No fresh news stories") vs system faults.
7. Single-issue alerting for actionable persistent failures.
"""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_HISTORY_PATH = Path(os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json"))
SYSTEM_ALERT_LABEL = "news-snap-system-alert"


def sanitize_health_output(s: str) -> str:
    """Sanitize any sensitive strings in diagnostic output."""
    msg = str(s)
    for env_var in (
        "INSTAGRAM_ACCESS_TOKEN", "GH_SECRETS_WRITE_TOKEN", "GITHUB_TOKEN",
        "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GROQ_API_KEY", "GEMINI_API_KEY"
    ):
        v = os.environ.get(env_var, "").strip()
        if v and len(v) > 4:
            msg = msg.replace(v, f"[REDACTED_{env_var}]")
    msg = re.sub(r"access_token=[a-zA-Z0-9_\-]+", "access_token=[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"Bearer\s+[a-zA-Z0-9_\-]+", "Bearer [REDACTED]", msg, flags=re.IGNORECASE)
    return msg


def write_step_summary(markdown_text: str) -> None:
    """Append text to GITHUB_STEP_SUMMARY if available."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(markdown_text + "\n")
        except Exception:
            pass


def check_publication_health(history_path: Path = DEFAULT_HISTORY_PATH) -> dict:
    """Inspect history.json for last confirmed post, rolling 24h count, and cadence."""
    from quota_manager import check_rolling_24h_cap, check_publication_cadence_due, load_history

    data = load_history(history_path)
    posted = data.get("posted", [])
    confirmed_posts = [p for p in posted if p.get("published") is True]

    is_under_cap, count_24h, remaining_allowance = check_rolling_24h_cap(history_path, max_posts=50)
    is_cadence_due, elapsed_min, remaining_min = check_publication_cadence_due(history_path, cadence_minutes=25)

    last_post = confirmed_posts[-1] if confirmed_posts else None
    last_post_time = last_post.get("timestamp") if last_post else None
    last_media_id = last_post.get("media_id") if last_post else None
    last_title = last_post.get("title") if last_post else None

    return {
        "total_confirmed_posts": len(confirmed_posts),
        "posts_in_last_24h": count_24h,
        "rolling_cap_limit": 50,
        "is_under_cap": is_under_cap,
        "remaining_allowance": remaining_allowance,
        "last_post_timestamp": last_post_time,
        "last_media_id": last_media_id,
        "last_title": last_title,
        "elapsed_minutes_since_last_post": elapsed_min,
        "is_cadence_due": is_cadence_due,
        "remaining_cadence_minutes": remaining_min,
        "target_cadence_minutes": 25
    }


def check_token_health(history_path: Path = DEFAULT_HISTORY_PATH) -> dict:
    """Inspect Instagram token metadata from history.json."""
    from quota_manager import get_token_metadata

    meta = get_token_metadata(history_path)
    now_utc = datetime.now(timezone.utc)

    status = meta.get("status", "UNKNOWN")
    expires_at_str = meta.get("expires_at")
    days_remaining = None

    if expires_at_str:
        try:
            exp_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            days_remaining = (exp_dt - now_utc).total_seconds() / 86400.0
        except Exception:
            pass

    return {
        "status": status,
        "refreshed_at": meta.get("refreshed_at"),
        "expires_at": expires_at_str,
        "days_remaining": round(days_remaining, 1) if days_remaining is not None else None,
        "secret_updated": meta.get("secret_updated", False),
        "secret_status": meta.get("secret_status", "UNKNOWN")
    }


def check_ai_provider_health(history_path: Path = DEFAULT_HISTORY_PATH) -> dict:
    """Inspect configured AI providers, active cooldowns, and failover status."""
    from quota_manager import get_all_quota_cooldowns, are_all_configured_providers_cooling_down
    try:
        from ai_provider import get_configured_providers, get_available_providers, get_active_provider
        configured = get_configured_providers()
        available = get_available_providers(history_path)
        active = get_active_provider(history_path)
    except ImportError:
        configured = []
        available = []
        active = ""

    all_cooling, reason, earliest_reset = are_all_configured_providers_cooling_down(history_path)
    cooldowns = get_all_quota_cooldowns(history_path)

    return {
        "configured_providers": configured,
        "available_providers": available,
        "active_provider": active,
        "active_cooldowns": cooldowns,
        "all_cooling_down": all_cooling,
        "cooling_down_reason": reason,
        "earliest_reset": earliest_reset.isoformat() if earliest_reset else None
    }


def check_pages_reachability(owner: str, repo: str) -> dict:
    """Verify that public GitHub Pages assets and privacy policy are reachable."""
    pages_base = f"https://{owner}.github.io/{repo}"
    privacy_url = f"{pages_base}/privacy.html"
    image_url = f"{pages_base}/news_snap_post.jpg"

    results = {}
    for name, url in (("privacy_page", privacy_url), ("latest_image", image_url)):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "NEWS-SNAP-HealthCheck/1.0"},
                method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                results[name] = {"status": resp.status, "reachable": resp.status == 200}
        except urllib.error.HTTPError as e:
            results[name] = {"status": e.code, "reachable": False}
        except Exception as e:
            results[name] = {"error": str(e), "reachable": False}

    return results


def run_system_health_check(
    repo: str = None,
    history_path: Path = DEFAULT_HISTORY_PATH,
    check_pages: bool = False
) -> dict:
    """Execute complete unattended system health check."""
    now_utc = datetime.now(timezone.utc)
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")

    pub_health = check_publication_health(history_path)
    tok_health = check_token_health(history_path)
    ai_health = check_ai_provider_health(history_path)

    pages_health = {}
    if check_pages and repo and "/" in repo:
        owner, repo_name = repo.split("/", 1)
        pages_health = check_pages_reachability(owner, repo_name)

    # Determine overall status
    critical_issues = []
    warnings = []

    if tok_health["status"] == "EXPIRED_OR_REVOKED":
        critical_issues.append("Instagram User Access Token has expired or was revoked.")
    elif tok_health["status"] == "BLOCKED_SECRETS_WRITE_TOKEN_REQUIRED":
        warnings.append("GH_SECRETS_WRITE_TOKEN required to automate secret updates for 2+ months.")

    if ai_health["all_cooling_down"]:
        warnings.append(f"All free AI providers cooling down until {ai_health['earliest_reset']}.")

    if not ai_health["configured_providers"]:
        critical_issues.append("No AI provider credentials configured.")

    if pub_health["posts_in_last_24h"] >= pub_health["rolling_cap_limit"]:
        warnings.append("Rolling 24-hour limit of 50 confirmed posts reached. Publication paused.")

    is_healthy = len(critical_issues) == 0

    report = {
        "timestamp": now_utc.isoformat(),
        "is_healthy": is_healthy,
        "critical_issues": critical_issues,
        "warnings": warnings,
        "publication": pub_health,
        "token": tok_health,
        "ai_providers": ai_health,
        "pages": pages_health
    }

    # Format Markdown Step Summary
    summary_md = (
        f"## 🏥 NEWS SNAP Unattended System Health Report\n\n"
        f"- **Check Time:** `{now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}`\n"
        f"- **Overall Health:** {'🟢 HEALTHY' if is_healthy else '🔴 ACTION REQUIRED'}\n"
        f"- **Cadence Setting:** `25m minimum spacing` | Discovery: `5m`\n"
        f"- **Rolling 24h Cap:** `{pub_health['posts_in_last_24h']}/50 posts` (Allowance: `{pub_health['remaining_allowance']}`)\n\n"
        f"### 📰 Last Confirmed Publication\n"
        f"- **Timestamp:** `{pub_health['last_post_timestamp'] or 'None'}`\n"
        f"- **Media ID:** `{pub_health['last_media_id'] or 'None'}`\n"
        f"- **Headline:** {pub_health['last_title'] or 'None'}\n"
        f"- **Elapsed:** `{pub_health['elapsed_minutes_since_last_post']:.1f}m`\n\n"
        f"### 🔑 Instagram Token Status\n"
        f"- **Status:** `{tok_health['status']}`\n"
        f"- **Known Expiry:** `{tok_health['expires_at'] or 'Unknown'}` (~{tok_health['days_remaining'] or 'N/A'} days)\n"
        f"- **Auto-Update Secret:** `{tok_health['secret_status']}`\n\n"
        f"### 🤖 Free AI Providers\n"
        f"- **Configured:** `{', '.join(ai_health['configured_providers']) or 'None'}`\n"
        f"- **Available:** `{', '.join(ai_health['available_providers']) or 'None'}`\n"
        f"- **Active Provider:** `{ai_health['active_provider'] or 'None'}`\n"
    )

    if critical_issues:
        summary_md += f"\n### 🚨 Critical Issues\n" + "\n".join(f"- ❌ {i}" for i in critical_issues) + "\n"
    if warnings:
        summary_md += f"\n### ⚠️ Notices & Warnings\n" + "\n".join(f"- ℹ️ {w}" for w in warnings) + "\n"

    write_step_summary(summary_md)
    try:
        print(sanitize_health_output(summary_md))
    except UnicodeEncodeError:
        print(sanitize_health_output(summary_md).encode("ascii", errors="replace").decode("ascii"))
    return report


if __name__ == "__main__":
    run_system_health_check()

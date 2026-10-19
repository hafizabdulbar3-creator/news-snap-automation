"""NEWS SNAP - Independent Recovery Watchdog.

Monitors the health of the NEWS SNAP Scheduler Controller.
Serves strictly as a resilient fail-safe mechanism, not as the primary 5-minute trigger.

Watchdog Behavior:
1. Queries the GitHub API for existing runs of 'news-snap-scheduler.yml'.
2. If any controller run is currently active ('in_progress' or 'queued'), it does nothing.
3. If no controller is active, checks the completion timestamp of the latest run:
   - If completed within the stale threshold (default 12 minutes), does nothing.
   - If no run exists or the last run is older than the stale threshold, it dispatches
     a replacement controller run to revive the chain.
4. Uses the standard repository-scoped GITHUB_TOKEN.
5. Does NOT dispatch the production publisher directly; only revives the controller.

To stop the scheduler safely:
1. Navigate to GitHub Actions in your repository.
2. Disable the workflow 'NEWS SNAP Scheduler Controller'.
3. Disable the workflow 'NEWS SNAP Scheduler Watchdog'.
4. Cancel any running controller workflow run.
"""

from datetime import datetime, timezone
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_CONTROLLER_WORKFLOW = "news-snap-scheduler.yml"
DEFAULT_STALE_THRESHOLD_MINUTES = 12


def parse_github_timestamp(ts_str: str) -> datetime:
    """Parse a GitHub ISO 8601 timestamp string into a timezone-aware UTC datetime."""
    if not ts_str:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        # Fallback parsing
        clean_str = ts_str.split(".")[0]
        return datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def query_api(url: str, token: str, method: str = "GET", payload: dict = None) -> tuple[int, dict]:
    """Execute a GitHub API HTTP request and return (status_code, response_json)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "NEWS-SNAP-Watchdog/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            body = resp.read()
            if body:
                try:
                    return status, json.loads(body.decode("utf-8"))
                except Exception:
                    return status, {"raw": body.decode("utf-8", errors="ignore")}
            return status, {}
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        return err.code, {"error": str(err), "body": body}
    except Exception as exc:
        return 0, {"error": str(exc)}


def run_watchdog_check(
    repo: str = None,
    token: str = None,
    controller_workflow: str = DEFAULT_CONTROLLER_WORKFLOW,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    api_url: str = DEFAULT_API_URL,
    history_file: str = None
) -> dict:
    """Check health of the controller chain and revive it if demonstrably stale."""
    now_utc = datetime.now(timezone.utc)
    print("===== NEWS SNAP SCHEDULER WATCHDOG =====")
    print(f"Watchdog inspection at: {now_utc.isoformat()}")

    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")

    if not repo:
        raise ValueError("GITHUB_REPOSITORY is required")
    if not token:
        raise ValueError("GITHUB_TOKEN is required")

    print(f"Repository: {repo}")
    print(f"Monitored Controller: {controller_workflow}")
    print(f"Stale Threshold: {stale_threshold_minutes} minutes")

    # 1. Check for active quota cooldown
    history_file = history_file or os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
    try:
        from quota_manager import is_cooldown_active, get_quota_cooldown
        if is_cooldown_active(history_file):
            cd = get_quota_cooldown(history_file)
            resets_at = cd.get("resets_at", "unknown")
            reason = cd.get("reason", "Daily quota exhausted")
            print(f"[WATCHDOG COOLDOWN ACTIVE] Active Gemini quota cooldown until {resets_at}.")
            print(f"[WATCHDOG COOLDOWN ACTIVE] Reason: {reason}")
            print("[WATCHDOG COOLDOWN ACTIVE] Suppressing scheduler revival while quota cooldown remains active.")
            print("===== WATCHDOG INSPECTION COMPLETE (COOLDOWN ACTIVE) =====")
            return {
                "status": "cooldown_active",
                "action": "none",
                "resets_at": resets_at,
                "reason": reason
            }
    except ImportError:
        pass

    # Fetch recent controller workflow runs
    url = f"{api_url}/repos/{repo}/actions/workflows/{controller_workflow}/runs?per_page=15"
    status, data = query_api(url, token, method="GET")
    if status != 200:
        error_msg = f"Failed to fetch runs for '{controller_workflow}' (HTTP {status}): {data.get('body') or data.get('error')}"
        raise RuntimeError(error_msg)

    runs = data.get("workflow_runs", [])

    # Check for active or queued runs
    active_runs = [r for r in runs if r.get("status") in ("in_progress", "queued", "waiting", "requested")]
    if active_runs:
        active = active_runs[0]
        print(f"[WATCHDOG OK] Controller run #{active.get('run_number')} (ID: {active.get('id')}) is currently '{active.get('status')}'.")
        print("[WATCHDOG OK] Recurrence chain is active. No intervention needed.")
        return {
            "status": "healthy",
            "action": "none",
            "active_run_id": active.get("id"),
            "active_status": active.get("status")
        }

    # If no active runs, inspect the latest completed run
    completed_runs = [r for r in runs if r.get("status") == "completed"]
    if completed_runs:
        latest = completed_runs[0]
        finish_time_str = latest.get("updated_at") or latest.get("created_at")
        finish_time = parse_github_timestamp(finish_time_str)
        elapsed_seconds = (now_utc - finish_time).total_seconds()
        elapsed_minutes = elapsed_seconds / 60.0

        if elapsed_minutes < stale_threshold_minutes:
            print(f"[WATCHDOG OK] Last controller run #{latest.get('run_number')} completed {elapsed_minutes:.1f} minutes ago.")
            print(f"[WATCHDOG OK] Elapsed time is within the {stale_threshold_minutes}-minute threshold. Chain is healthy.")
            return {
                "status": "healthy",
                "action": "none",
                "last_run_id": latest.get("id"),
                "elapsed_minutes": elapsed_minutes
            }

        print(f"[WATCHDOG STALE] Last controller run #{latest.get('run_number')} completed {elapsed_minutes:.1f}m ago (exceeds {stale_threshold_minutes}m threshold).")
    else:
        print("[WATCHDOG STALE] No completed controller runs found in history.")

    # Chain is stale or absent: dispatch replacement controller in safe bootstrap mode
    print(f"[WATCHDOG RECOVERY] Cooldown check confirmed expired/clear. Reviving scheduler chain by dispatching safe bootstrap...")
    dispatch_url = f"{api_url}/repos/{repo}/actions/workflows/{controller_workflow}/dispatches"
    payload = {
        "ref": "main",
        "inputs": {"bootstrap_only": True}
    }
    dispatch_status, dispatch_resp = query_api(dispatch_url, token, method="POST", payload=payload)
    if dispatch_status == 204:
        print(f"[WATCHDOG REVIVED] Successfully dispatched safe bootstrap controller run.")
        print("===== WATCHDOG INSPECTION COMPLETE =====")
        return {
            "status": "revived",
            "action": "dispatched_bootstrap",
            "controller_workflow": controller_workflow
        }

    error_msg = f"Failed to dispatch replacement controller (HTTP {dispatch_status}): {dispatch_resp.get('body') or dispatch_resp.get('error')}"
    raise RuntimeError(error_msg)


if __name__ == "__main__":
    try:
        run_watchdog_check()
    except Exception as err:
        print(f"[WATCHDOG ERROR] Fatal failure during watchdog check: {err}", file=sys.stderr)
        sys.exit(1)

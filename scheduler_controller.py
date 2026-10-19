"""NEWS SNAP - Dedicated Scheduler Controller.

Self-perpetuating controller chain that ensures consistent ~5-minute production execution
without relying on GitHub Actions' delayed or dropped cron schedules.

Architecture:
1. Triggered via workflow_dispatch.
2. In 'bootstrap_only' mode:
   - Does NOT dispatch the production publisher (no Instagram publishing).
   - Safely initiates the recurrence chain by queuing the first real cycle.
3. In normal mode:
   - Dispatches the production workflow ('test.yml') exactly once.
   - Calculates remaining wait time (target 300s minus elapsed execution time).
   - Queues the successor controller run with 'bootstrap_only=false'.
4. Prevents duplicate chains:
   - Checks if another controller run is already active or queued before proceeding.
5. Error handling:
   - Validates all GitHub API response status codes (expects HTTP 204 for dispatch).
   - Raises descriptive errors on failures rather than claiming false success.

To stop the scheduler:
1. Disable 'NEWS SNAP Scheduler Controller' workflow in GitHub Actions.
2. Disable 'NEWS SNAP Scheduler Watchdog' workflow in GitHub Actions.
3. Cancel any currently running controller run in GitHub Actions UI.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_PUBLISHER_WORKFLOW = "test.yml"
DEFAULT_CONTROLLER_WORKFLOW = "news-snap-scheduler.yml"
DEFAULT_CYCLE_INTERVAL = 300  # 5 minutes
MIN_SLEEP_SECONDS = 5


def get_auth_headers(token: str) -> dict:
    """Build standard GitHub REST API request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "NEWS-SNAP-Scheduler/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def query_api(url: str, token: str, method: str = "GET", payload: dict = None) -> tuple[int, dict]:
    """Execute a GitHub API HTTP request and return (status_code, response_json)."""
    headers = get_auth_headers(token)
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


def check_active_controller_runs(
    repo: str,
    token: str,
    controller_workflow: str = DEFAULT_CONTROLLER_WORKFLOW,
    current_run_id: str = "",
    api_url: str = DEFAULT_API_URL
) -> list:
    """Check for active or queued controller runs other than the current one."""
    url = f"{api_url}/repos/{repo}/actions/workflows/{controller_workflow}/runs?per_page=10"
    status, data = query_api(url, token, method="GET")
    if status != 200:
        print(f"[WARN] Unable to fetch controller runs (HTTP {status}): {data.get('error', '')}")
        return []

    other_active = []
    current_id_int = int(current_run_id) if current_run_id and current_run_id.isdigit() else None
    for run in data.get("workflow_runs", []):
        run_status = run.get("status", "")
        run_id = run.get("id")
        if run_status in ("in_progress", "queued", "waiting", "requested"):
            if current_id_int is not None and run_id == current_id_int:
                continue
            other_active.append(run)
    return other_active


def dispatch_workflow(
    repo: str,
    token: str,
    workflow_file: str,
    ref: str = "main",
    inputs: dict = None,
    api_url: str = DEFAULT_API_URL
) -> bool:
    """Dispatch a workflow via workflow_dispatch API. Returns True on success, raises RuntimeError on failure."""
    url = f"{api_url}/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs

    status, resp = query_api(url, token, method="POST", payload=payload)
    if status == 204:
        return True
    error_msg = f"Failed to dispatch '{workflow_file}' (HTTP {status}): {resp.get('body') or resp.get('error', 'Unknown error')}"
    raise RuntimeError(error_msg)


def run_controller_cycle(
    repo: str = None,
    token: str = None,
    current_run_id: str = None,
    bootstrap_only: bool = None,
    cycle_interval: int = DEFAULT_CYCLE_INTERVAL,
    min_sleep: int = MIN_SLEEP_SECONDS,
    publisher_workflow: str = DEFAULT_PUBLISHER_WORKFLOW,
    controller_workflow: str = DEFAULT_CONTROLLER_WORKFLOW,
    api_url: str = DEFAULT_API_URL,
    sleep_fn=time.sleep,
    history_file: str = None
) -> dict:
    """Execute a single cycle of the scheduler controller."""
    start_time = time.time()
    now_utc = datetime.now(timezone.utc).isoformat()
    print(f"===== NEWS SNAP SCHEDULER CONTROLLER =====")
    print(f"Cycle started at: {now_utc}")

    # Resolve configuration from arguments or environment
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    current_run_id = current_run_id or os.environ.get("GITHUB_RUN_ID", "")

    if bootstrap_only is None:
        raw_boot = str(os.environ.get("BOOTSTRAP_ONLY", "false")).strip().lower()
        bootstrap_only = raw_boot in ("true", "1", "yes")

    if not repo:
        raise ValueError("GITHUB_REPOSITORY is required")
    if not token:
        raise ValueError("GITHUB_TOKEN is required")

    print(f"Repository: {repo}")
    print(f"Current Run ID: {current_run_id or 'local/mock'}")
    print(f"Mode: {'BOOTSTRAP ONLY (Safe Init)' if bootstrap_only else 'NORMAL (Publish + Recur)'}")

    # Guard against duplicate concurrent chains
    other_active = check_active_controller_runs(
        repo=repo,
        token=token,
        controller_workflow=controller_workflow,
        current_run_id=current_run_id,
        api_url=api_url
    )
    if other_active:
        current_id_int = int(current_run_id) if current_run_id and str(current_run_id).isdigit() else None
        if current_id_int and all(int(r.get("id", 0)) < current_id_int for r in other_active):
            print("[DUPLICATE CHAIN GUARD] Detected older predecessor run still in teardown; waiting 8s for status propagation...")
            sleep_fn(8)
            other_active = check_active_controller_runs(
                repo=repo,
                token=token,
                controller_workflow=controller_workflow,
                current_run_id=current_run_id,
                api_url=api_url
            )

    if other_active:
        other_run = other_active[0]
        print(f"[DUPLICATE CHAIN GUARD] Active controller run #{other_run.get('run_number')} (ID: {other_run.get('id')}) is already {other_run.get('status')}.")
        print("[DUPLICATE CHAIN GUARD] Aborting this run to preserve strict single-chain serialization.")
        return {
            "status": "aborted_duplicate",
            "active_run_id": other_run.get("id"),
            "publisher_dispatched": False,
            "successor_dispatched": False
        }

    # FAIL-CLOSED QUOTA & INTEGRITY GUARD
    # If quota checking fails, history.json is unreadable or malformed,
    # or quota_manager cannot be imported, controller MUST NOT dispatch publisher or successor.
    history_file = history_file or os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
    try:
        hist_path = Path(history_file)
        if not hist_path.is_file():
            diag = f"[QUOTA GUARD FAIL-CLOSED] History file missing or not accessible: '{history_file}'"
            print(diag)
            print("[CHAIN HALT] Aborting controller cycle without dispatching publisher or successor.")
            return {
                "status": "error_history_missing",
                "error": diag,
                "publisher_dispatched": False,
                "successor_dispatched": False
            }

        try:
            raw_hist = hist_path.read_text(encoding="utf-8")
            data = json.loads(raw_hist)
            if not isinstance(data, dict):
                raise ValueError("History file root must be a JSON object")
        except Exception as json_err:
            diag = f"[QUOTA GUARD FAIL-CLOSED] History file unreadable or malformed JSON: {json_err}"
            print(diag)
            print("[CHAIN HALT] Aborting controller cycle without dispatching publisher or successor.")
            return {
                "status": "error_history_malformed",
                "error": diag,
                "publisher_dispatched": False,
                "successor_dispatched": False
            }

        try:
            from quota_manager import is_cooldown_active, get_quota_cooldown
        except Exception as import_err:
            diag = f"[QUOTA GUARD FAIL-CLOSED] Quota module could not be imported: {import_err}"
            print(diag)
            print("[CHAIN HALT] Aborting controller cycle without dispatching publisher or successor.")
            return {
                "status": "error_quota_module_import",
                "error": diag,
                "publisher_dispatched": False,
                "successor_dispatched": False
            }

        active_provider = None
        try:
            from ai_provider import get_active_provider
            active_provider = get_active_provider() or None
        except ImportError:
            pass

        if is_cooldown_active(history_file, provider=active_provider):
            cd = get_quota_cooldown(history_file, provider=active_provider)
            resets_at = cd.get("resets_at", "unknown")
            reason = cd.get("reason", "Daily quota exhausted")
            prov_name = cd.get("provider", active_provider or "AI provider").upper()
            print(f"[QUOTA COOLDOWN ACTIVE] Production publishing workflow dispatch suppressed ({prov_name}).")
            print(f"[RESET TIME] {resets_at}")
            print(f"[REASON] {reason}")
            print("[CHAIN HALT] Stopping 5-minute recurrence chain to prevent repeated no-op executions.")
            print("===== CONTROLLER PAUSED (QUOTA COOLDOWN) =====")
            return {
                "status": "paused_quota_cooldown",
                "resets_at": resets_at,
                "reason": reason,
                "provider": prov_name,
                "publisher_dispatched": False,
                "successor_dispatched": False
            }
    except Exception as guard_err:
        diag = f"[QUOTA GUARD FAIL-CLOSED] Unexpected error during quota verification: {guard_err}"
        print(diag)
        print("[CHAIN HALT] Aborting controller cycle without dispatching publisher or successor.")
        return {
            "status": "error_quota_guard_failed",
            "error": diag,
            "publisher_dispatched": False,
            "successor_dispatched": False
        }

    publisher_dispatched = False
    # Execute publisher dispatch if not in bootstrap mode
    if bootstrap_only:
        print("[BOOTSTRAP] Safe bootstrap active: Skipping production publisher dispatch.")
        print("[BOOTSTRAP] No Instagram publishing will occur in this cycle.")
    else:
        print(f"[PUBLISHER] Dispatching production publishing workflow '{publisher_workflow}'...")
        dispatch_workflow(
            repo=repo,
            token=token,
            workflow_file=publisher_workflow,
            ref="main",
            api_url=api_url
        )
        publisher_dispatched = True
        print(f"[PUBLISHER DISPATCHED] Successfully triggered '{publisher_workflow}' via workflow_dispatch.")

    # Calculate remaining sleep time to maintain 5-minute recurrence cadence
    elapsed = time.time() - start_time
    remaining = cycle_interval - elapsed
    sleep_duration = max(remaining, min_sleep) if cycle_interval > 0 else 0

    print(f"[CADENCE] Cycle elapsed time: {elapsed:.2f}s | Target interval: {cycle_interval}s")
    if sleep_duration > 0:
        print(f"[CADENCE] Waiting {sleep_duration:.1f}s before scheduling successor...")
        sleep_fn(sleep_duration)

    # Double check no duplicate successor has been launched while we waited
    final_check = check_active_controller_runs(
        repo=repo,
        token=token,
        controller_workflow=controller_workflow,
        current_run_id=current_run_id,
        api_url=api_url
    )
    if final_check:
        other_run = final_check[0]
        print(f"[DUPLICATE GUARD] Successor already detected (Run #{other_run.get('run_number')}). Skipping duplicate successor dispatch.")
        return {
            "status": "success",
            "publisher_dispatched": publisher_dispatched,
            "successor_dispatched": False,
            "duplicate_prevented": True
        }

    # Dispatch successor controller run with bootstrap_only=false
    print(f"[SUCCESSOR] Dispatching next controller run with bootstrap_only=false...")
    dispatch_workflow(
        repo=repo,
        token=token,
        workflow_file=controller_workflow,
        ref="main",
        inputs={"bootstrap_only": False},
        api_url=api_url
    )
    print(f"[SUCCESSOR DISPATCHED] Next controller cycle successfully queued.")
    print("===== CONTROLLER CYCLE COMPLETE =====")

    return {
        "status": "success",
        "publisher_dispatched": publisher_dispatched,
        "successor_dispatched": True,
        "elapsed_seconds": time.time() - start_time
    }


if __name__ == "__main__":
    try:
        run_controller_cycle()
    except Exception as err:
        print(f"[CONTROLLER ERROR] Fatal failure during controller cycle: {err}", file=sys.stderr)
        sys.exit(1)

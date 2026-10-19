"""NEWS SNAP - Cloudflare Workers AI Smoke Test.

Makes a single minimal text-generation request to Cloudflare Workers AI
using the configured model and reports only success or failure.

Guarantees:
- Never publishes to Instagram.
- Never imports or executes instagram_publisher.
- Never touches or alters production history (history.json).
- Never prints or exposes secret credentials.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Redirect any history tracking to an isolated temp directory to protect production history.json
temp_dir = tempfile.TemporaryDirectory()
os.environ["NEWS_SNAP_HISTORY_PATH"] = str(Path(temp_dir.name) / "smoke_history.json")


def run_smoke_test() -> int:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()

    if not token or not account_id:
        print("[SMOKE TEST FAILED] Required Cloudflare credentials missing from environment.")
        return 1

    try:
        import ai_provider

        # Make one minimal text-generation request
        test_prompt = 'Reply with a single JSON object: {"status": "ok", "provider": "cloudflare"}'
        result = ai_provider.call_cloudflare_chat_completion(
            prompt=test_prompt,
            system_prompt="You are a lightweight test service. Always output valid JSON.",
            max_tokens=60,
            max_attempts=2
        )

        if isinstance(result, dict) and (result.get("status") == "ok" or "status" in result or len(result) > 0):
            print("[SMOKE TEST SUCCESS] Cloudflare Workers AI responded successfully.")
            return 0
        else:
            print("[SMOKE TEST FAILED] Cloudflare Workers AI response was empty or malformed.")
            return 1

    except Exception as e:
        # Sanitize error to prevent leaking secrets in logs
        sanitized = ""
        try:
            import ai_provider
            sanitized = ai_provider.sanitize_ai_error(e)
        except Exception:
            sanitized = str(e)
            if token:
                sanitized = sanitized.replace(token, "[REDACTED_CLOUDFLARE_TOKEN]")
            if account_id:
                sanitized = sanitized.replace(account_id, "[REDACTED_CLOUDFLARE_ACCOUNT_ID]")

        print(f"[SMOKE TEST FAILED] Cloudflare API error: {sanitized}")
        return 1

    finally:
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(run_smoke_test())

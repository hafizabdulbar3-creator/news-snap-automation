"""NEWS SNAP — Safe Read-Only Instagram Meta Graph API Diagnostic Tool.

Performs read-only diagnostic checks against Meta Graph API endpoints using existing
INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID secrets.
Strictly safeguards credentials: NEVER prints or logs raw access tokens or sensitive values.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


def mask_token(token: str) -> str:
    if not token or not isinstance(token, str):
        return ""
    clean = token.strip()
    if len(clean) <= 8:
        return "***"
    return f"{clean[:4]}...{clean[-4:]}"


def sanitize(text: str, token: str = "") -> str:
    if not text:
        return ""
    s = str(text)
    if token and len(token) > 4:
        s = s.replace(token, mask_token(token))
    s = re.sub(r'access_token=([^&\s"\'\\}]+)', lambda m: f"access_token={mask_token(m.group(1))}", s)
    s = re.sub(r'("access_token"\s*:\s*")([^"\s]+)(")', lambda m: f'{m.group(1)}{mask_token(m.group(2))}{m.group(3)}', s)
    s = re.sub(r'(Bearer\s+)([A-Za-z0-9_\-\.]+)', lambda m: f'{m.group(1)}{mask_token(m.group(2))}', s)
    return s


def run_get_check(
    name: str,
    url: str,
    headers: dict = None,
    token: str = ""
) -> dict:
    req_headers = {"User-Agent": "NEWS-SNAP-Diagnostic/1.0"}
    if headers:
        req_headers.update(headers)

    display_url = sanitize(url, token)
    display_headers = {k: sanitize(v, token) for k, v in req_headers.items()}
    print(f"\n--- [TEST] {name} ---")
    print(f"URL: {display_url}")
    print(f"Headers: {display_headers}")

    req = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body_bytes = resp.read()
            resp_headers = dict(resp.headers)
            body_str = body_bytes.decode("utf-8", errors="replace")
            try:
                data = json.loads(body_str)
            except Exception:
                data = {"raw": body_str}

            print(f"RESULT: HTTP {status} (SUCCESS)")
            # Print safe headers
            for h in ("www-authenticate", "x-fb-debug", "x-app-usage"):
                if h in resp_headers:
                    print(f"Header {h}: {sanitize(resp_headers[h], token)}")
            print(f"Response: {sanitize(json.dumps(data, indent=2), token)}")
            return {"name": name, "success": True, "status": status, "data": data}
    except urllib.error.HTTPError as err:
        body_bytes = err.read()
        err_headers = dict(err.headers)
        body_str = body_bytes.decode("utf-8", errors="replace")
        try:
            err_data = json.loads(body_str)
        except Exception:
            err_data = {"raw": body_str}

        print(f"RESULT: HTTP {err.code} {err.reason} (FAILED)")
        for h in ("www-authenticate", "x-fb-debug", "x-app-usage"):
            if h in err_headers:
                print(f"Header {h}: {sanitize(err_headers[h], token)}")
        
        err_obj = err_data.get("error", {}) if isinstance(err_data, dict) else {}
        print(f"Error Message: {err_obj.get('message', 'N/A')}")
        print(f"Error Type: {err_obj.get('type', 'N/A')}")
        print(f"Error Code: {err_obj.get('code', 'N/A')}")
        print(f"Error Subcode: {err_obj.get('error_subcode', 'N/A')}")
        print(f"Error User Title: {err_obj.get('error_user_title', 'N/A')}")
        print(f"Error User Msg: {err_obj.get('error_user_msg', 'N/A')}")
        print(f"FB Trace ID: {err_obj.get('fbtrace_id', 'N/A')}")
        return {"name": name, "success": False, "status": err.code, "error": err_obj, "headers": err_headers}
    except Exception as exc:
        print(f"RESULT: Network/Execution Error: {sanitize(str(exc), token)}")
        return {"name": name, "success": False, "status": 0, "error": sanitize(str(exc), token)}


def main():
    print("=================================================================")
    print("NEWS SNAP - SAFE META GRAPH API READ-ONLY DIAGNOSTIC")
    print("=================================================================")

    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "").strip()

    print(f"Token Present: {bool(token)} (Masked: {mask_token(token)})")
    print(f"Token Length: {len(token)} chars")
    if token:
        prefix = token[:4] if len(token) >= 4 else "short"
        print(f"Token Prefix: {prefix} ({'Instagram Login User Token' if prefix.startswith('IG') else 'Facebook Login Token' if prefix.startswith('EA') else 'Other/Unknown'})")
    print(f"Configured Account ID Present: {bool(account_id)} (Length: {len(account_id)})")

    if not token:
        print("\n[FATAL] INSTAGRAM_ACCESS_TOKEN is missing. Cannot perform diagnostics.")
        sys.exit(1)

    results = []

    # 1. Instagram Graph Host (graph.instagram.com) with Bearer Header
    url_me_bearer = "https://graph.instagram.com/v22.0/me?fields=id,user_id,username,name,account_type"
    results.append(run_get_check(
        "graph.instagram.com /me (Bearer Header)",
        url_me_bearer,
        headers={"Authorization": f"Bearer {token}"},
        token=token
    ))

    # 2. Instagram Graph Host (graph.instagram.com) with Query Parameter
    url_me_query = f"https://graph.instagram.com/v22.0/me?fields=id,user_id,username,name,account_type&access_token={urllib.parse.quote(token)}"
    results.append(run_get_check(
        "graph.instagram.com /me (Query Param)",
        url_me_query,
        token=token
    ))

    # 3. Instagram Graph Host /me/permissions with Query Parameter
    url_me_perms_query = f"https://graph.instagram.com/v22.0/me/permissions?access_token={urllib.parse.quote(token)}"
    results.append(run_get_check(
        "graph.instagram.com /me/permissions (Query Param)",
        url_me_perms_query,
        token=token
    ))

    # 4. If account ID exists: content_publishing_limit on graph.instagram.com
    if account_id:
        url_pub_limit_ig_query = f"https://graph.instagram.com/v22.0/{account_id}/content_publishing_limit?fields=config,quota_usage&access_token={urllib.parse.quote(token)}"
        results.append(run_get_check(
            f"graph.instagram.com /{account_id}/content_publishing_limit (Query Param)",
            url_pub_limit_ig_query,
            token=token
        ))

        url_pub_limit_ig_bearer = f"https://graph.instagram.com/v22.0/{account_id}/content_publishing_limit?fields=config,quota_usage"
        results.append(run_get_check(
            f"graph.instagram.com /{account_id}/content_publishing_limit (Bearer Header)",
            url_pub_limit_ig_bearer,
            headers={"Authorization": f"Bearer {token}"},
            token=token
        ))

    # 5. Facebook Graph Host (graph.facebook.com) with Query Parameter
    url_fb_me_query = f"https://graph.facebook.com/v22.0/me?fields=id,name&access_token={urllib.parse.quote(token)}"
    results.append(run_get_check(
        "graph.facebook.com /me (Query Param)",
        url_fb_me_query,
        token=token
    ))

    # 6. Facebook Graph Host /me/permissions with Query Parameter
    url_fb_perms_query = f"https://graph.facebook.com/v22.0/me/permissions?access_token={urllib.parse.quote(token)}"
    results.append(run_get_check(
        "graph.facebook.com /me/permissions (Query Param)",
        url_fb_perms_query,
        token=token
    ))

    # 7. Facebook Graph Host debug_token
    url_fb_debug_token = f"https://graph.facebook.com/v22.0/debug_token?input_token={urllib.parse.quote(token)}&access_token={urllib.parse.quote(token)}"
    results.append(run_get_check(
        "graph.facebook.com /debug_token (Self-check)",
        url_fb_debug_token,
        token=token
    ))

    # 8. Summary of diagnostic results
    print("\n=================================================================")
    print("DIAGNOSTIC SUMMARY")
    print("=================================================================")
    all_failed = True
    any_success = False
    for r in results:
        status_label = "PASS" if r.get("success") else f"FAIL (HTTP {r.get('status')})"
        print(f"- {r.get('name')}: {status_label}")
        if r.get("success"):
            any_success = True
            all_failed = False

    print("\nCONCLUSION:")
    if any_success:
        print("[SUCCESS FOUND] At least one endpoint or authentication format responded successfully!")
    else:
        print("[ALL ENDPOINTS BLOCKED / FAILED] Meta returned errors for all tested formats and endpoints.")
        # Inspect the primary error
        first_err = next((r.get("error") for r in results if isinstance(r.get("error"), dict) and r.get("error")), {})
        msg = first_err.get("message", "")
        code = first_err.get("code", "")
        subcode = first_err.get("error_subcode", "")
        print(f"Primary error: code={code}, subcode={subcode}, message='{msg}'")
    print("=================================================================")

    # Write sanitized report to disk
    report_data = {
        "token_prefix": token[:4] if len(token) >= 4 else "unknown",
        "token_length": len(token),
        "any_success": any_success,
        "all_failed": all_failed,
        "results": results
    }
    sanitized_report = json.loads(sanitize(json.dumps(report_data, ensure_ascii=False), token))
    with open("diagnostic_report.json", "w", encoding="utf-8") as f:
        json.dump(sanitized_report, f, indent=2, ensure_ascii=False)
    print("Saved sanitized diagnostic report to diagnostic_report.json")


if __name__ == "__main__":
    main()


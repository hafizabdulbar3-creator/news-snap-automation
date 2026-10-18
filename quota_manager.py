"""NEWS SNAP Quota & Classification Cache Manager.

Manages:
1. Shared quota cooldowns (parsing HTTP 429 response bodies for daily quota limits vs transient limits).
2. Persistent classified candidate pool in history.json so a single classification batch can power multiple runs.
3. Local journalistic heuristic triage as a zero-cost, zero-API pre-filter and fallback.
"""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import urllib.error

HISTORY_PATH = Path("history.json")


def extract_http_error_body(err: Exception) -> str:
    """Extract string body from urllib.error.HTTPError safely."""
    if not isinstance(err, urllib.error.HTTPError):
        return str(err)
    body = ""
    try:
        if hasattr(err, "read"):
            raw = err.read()
            body = raw.decode("utf-8", errors="replace")
    except Exception:
        pass
    if not body and hasattr(err, "reason"):
        body = str(err.reason)
    return body


def parse_quota_cooldown(err: Exception) -> tuple[bool, datetime | None, str]:
    """Examines an exception (e.g. HTTPError 429) to detect daily/long-term quota exhaustion.

    Returns:
        (is_exhausted, reset_datetime_utc, reason_description)
    """
    if not isinstance(err, urllib.error.HTTPError):
        return False, None, ""

    body = extract_http_error_body(err)
    body_low = body.lower()

    # Detect indicators of daily or long-term quota exhaustion
    is_daily = (
        "quota exceeded for metric" in body_low
        or "generaterequestsperday" in body_low
        or "free_tier_requests" in body_low
        or "limit: 20" in body_low
        or ("daily" in body_low and "quota" in body_low)
        or ("please retry in" in body_low and ("h" in body_low or "m" in body_low))
    )

    if not is_daily and err.code != 429:
        return False, None, ""

    # Check if this is a transient short-term burst rate limit instead of daily quota
    now = datetime.now(timezone.utc)
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", body, re.IGNORECASE)
    if m:
        h = int(m.group(1) or 0)
        mins = int(m.group(2) or 0)
        s = float(m.group(3) or 0)
        total_sec = h * 3600 + mins * 60 + s
        if total_sec > 0:
            reset_dt = now + timedelta(seconds=total_sec)
            reason = f"Gemini API quota exhausted. Retry required in {total_sec:.0f}s ({h}h {mins}m {s:.0f}s)."
            return True, reset_dt, reason

    # Check Retry-After header
    if err.headers:
        ra = err.headers.get("Retry-After")
        if ra:
            try:
                ra_sec = float(ra)
                if ra_sec >= 60:
                    reset_dt = now + timedelta(seconds=ra_sec)
                    return True, reset_dt, f"Gemini API Retry-After cooldown: {ra_sec:.0f}s."
            except ValueError:
                pass

    if is_daily:
        # Default daily reset is next 00:00 UTC (Midnight UTC)
        reset_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        reason = "Gemini Free Tier daily quota exhausted (limit: 20 requests/day). Resets at 00:00 UTC."
        return True, reset_dt, reason

    return False, None, ""


def load_history(history_path: Path = HISTORY_PATH) -> dict:
    """Safely load history.json structure."""
    p = Path(history_path)
    if not p.is_file():
        return {"posted": [], "processed": [], "classified_pool": [], "quota_cooldown": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"posted": [], "processed": [], "classified_pool": [], "quota_cooldown": {}}
        if "classified_pool" not in data:
            data["classified_pool"] = []
        if "quota_cooldown" not in data:
            data["quota_cooldown"] = {}
        return data
    except Exception:
        return {"posted": [], "processed": [], "classified_pool": [], "quota_cooldown": {}}


def save_history(data: dict, history_path: Path = HISTORY_PATH) -> None:
    """Save history.json with indentation."""
    p = Path(history_path)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_quota_cooldown(history_path: Path = HISTORY_PATH) -> dict:
    """Returns active cooldown info if currently in cooldown, else empty dict."""
    data = load_history(history_path)
    cd = data.get("quota_cooldown", {})
    if not cd or not cd.get("active"):
        return {}
    resets_at_str = cd.get("resets_at")
    if not resets_at_str:
        return {}
    try:
        resets_at = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if now < resets_at:
            return cd
        # Expired: clear active state
        cd["active"] = False
        data["quota_cooldown"] = cd
        save_history(data, history_path)
        return {}
    except Exception:
        return {}


def is_cooldown_active(history_path: Path = HISTORY_PATH) -> bool:
    """Check whether a Gemini API quota cooldown is currently active."""
    return bool(get_quota_cooldown(history_path))


def set_quota_cooldown(resets_at: datetime, reason: str, history_path: Path = HISTORY_PATH) -> None:
    """Set an active quota cooldown in history.json."""
    data = load_history(history_path)
    data["quota_cooldown"] = {
        "active": True,
        "resets_at": resets_at.isoformat(),
        "reason": reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_history(data, history_path)


def clear_quota_cooldown(history_path: Path = HISTORY_PATH) -> None:
    """Clear active quota cooldown in history.json."""
    data = load_history(history_path)
    if "quota_cooldown" in data:
        data["quota_cooldown"]["active"] = False
        save_history(data, history_path)


def get_classified_pool(history_path: Path = HISTORY_PATH) -> list:
    """Get all candidates currently stored in classified_pool."""
    data = load_history(history_path)
    return data.get("classified_pool", [])


def save_to_classified_pool(new_items: list, history_path: Path = HISTORY_PATH) -> int:
    """Append newly classified articles into classified_pool, avoiding duplicates.

    Returns the number of new items added.
    """
    if not new_items:
        return 0
    data = load_history(history_path)
    pool = data.get("classified_pool", [])

    existing_urls = {str(item.get("url", "")).strip().lower() for item in pool if item.get("url")}
    existing_titles = {str(item.get("title", "")).strip().lower() for item in pool if item.get("title")}

    # Also avoid anything already posted or processed
    for entry in data.get("posted", []):
        if entry.get("url"):
            existing_urls.add(str(entry["url"]).strip().lower())
        if entry.get("title"):
            existing_titles.add(str(entry["title"]).strip().lower())
    for entry in data.get("processed", []):
        if entry.get("url"):
            existing_urls.add(str(entry["url"]).strip().lower())
        if entry.get("title"):
            existing_titles.add(str(entry["title"]).strip().lower())

    added = 0
    for it in new_items:
        u = str(it.get("url", "")).strip().lower()
        t = str(it.get("title", "")).strip().lower()
        if not u or not t:
            continue
        if u in existing_urls or t in existing_titles:
            continue
        pool.append(it)
        existing_urls.add(u)
        existing_titles.add(t)
        added += 1

    data["classified_pool"] = pool
    save_history(data, history_path)
    return added


def remove_from_classified_pool(url: str, title: str = "", history_path: Path = HISTORY_PATH) -> None:
    """Remove a posted/selected article from classified_pool."""
    data = load_history(history_path)
    pool = data.get("classified_pool", [])
    u_low = str(url or "").strip().lower()
    t_low = str(title or "").strip().lower()

    new_pool = []
    for item in pool:
        item_u = str(item.get("url", "")).strip().lower()
        item_t = str(item.get("title", "")).strip().lower()
        if u_low and item_u == u_low:
            continue
        if t_low and item_t == t_low:
            continue
        new_pool.append(item)

    data["classified_pool"] = new_pool
    save_history(data, history_path)


def heuristic_classify_article(title: str, domain: str = "") -> dict:
    """Journalistic heuristic classifier.

    Categorizes headlines into MAJOR, NORMAL, or LOW using high-precision keyword patterns with 0 API calls.
    """
    t_low = title.lower()

    # Low-value filters (entertainment, horoscope, gossip, local crime trivia)
    low_patterns = (
        r"\b(horoscope|zodiac|tarot|astrology|rashifal)\b",
        r"\b(box office|trailer|teaser|release date|ott|actor|actress|bollywood|hollywood)\b",
        r"\b(wedding|dating|spotted|viral video|dance video|fashion|outfit)\b",
        r"\b(cricket|ipl|match highlights|vs|won by|wickets|premier league|football|goals)\b",
        r"\b(lottery|lucky draw|winning numbers)\b",
        r"\b(bizarre|shocking|you won't believe|secret behind)\b",
    )
    for pat in low_patterns:
        if re.search(pat, t_low):
            return {
                "importance": "LOW",
                "topic": "Entertainment / Lifestyle",
                "reason": "Filtered by local heuristic: entertainment, lifestyle, sports, or trivia content."
            }

    # Major-value filters (geopolitics, summits, elections, war, disaster, economy, breakthrough)
    major_patterns = [
        (r"\b(war|military|airstrike|airstrikes|invaded|invasion|missile|missiles|nuclear|troops|ceasefire|nato|security council|sanction|sanctions|conflict|frontline)\b", "Geopolitics & Defense"),
        (r"\b(national election|presidential election|prime minister|president|parliament|senate|congress|supreme court|cabinet|sworn in|resigns|impeached|treaty|accord|summit)\b", "Politics & Governance"),
        (r"\b(deadly fire|fatal crash|earthquake|tsunami|wildfire|casualties|death toll|killed in|dead in|mass casualty|catastrophe)\b", "Disaster & Emergency"),
        (r"\b(central bank|interest rate|federal reserve|inflation|recession|tariffs|gdp growth|sovereign debt)\b", "Economy & Trade"),
        (r"\b(scientific breakthrough|space agency|telescope|lunar mission|mars rover|fusion power)\b", "Science & Innovation"),
    ]

    for pat, topic in major_patterns:
        if re.search(pat, t_low):
            return {
                "importance": "MAJOR",
                "topic": topic,
                "reason": f"Classified by local heuristic as {topic}: high international public interest."
            }

    # Default to NORMAL if it is a legitimate news story
    return {
        "importance": "NORMAL",
        "topic": "World News",
        "reason": "Classified by local heuristic: standard national or international news report."
    }

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
    if hasattr(err, "_cached_body") and err._cached_body:
        return err._cached_body
    body = ""
    try:
        if hasattr(err, "read"):
            raw = err.read()
            if isinstance(raw, bytes):
                body = raw.decode("utf-8", errors="replace")
            else:
                body = str(raw)
            err._cached_body = body
    except Exception:
        pass
    if not body and hasattr(err, "reason"):
        body = str(err.reason)
    return body


def parse_quota_cooldown(err: Exception) -> tuple[bool, datetime | None, str]:
    """Examines an exception (e.g. HTTPError 429) to detect daily/long-term quota exhaustion.

    Supports both Groq and Gemini API error formats.

    Returns:
        (is_exhausted, reset_datetime_utc, reason_description)
    """
    if not isinstance(err, urllib.error.HTTPError):
        return False, None, ""

    body = extract_http_error_body(err)
    body_low = body.lower()

    # Determine provider hints
    url_str = str(getattr(err, "url", "")).lower()
    if "cloudflare" in url_str or "cloudflare" in body_low or "neuron" in body_low or "zai-org" in body_low or "glm" in body_low:
        provider = "Cloudflare"
    elif "groq.com" in url_str or "groq" in body_low or "llama" in body_low or "gpt-oss" in body_low or "rpd" in body_low or "tpd" in body_low:
        provider = "Groq"
    else:
        provider = "Gemini"

    # Detect indicators of daily or long-term quota exhaustion
    has_daily_metric = (
        "quota exceeded for metric" in body_low
        or "generaterequestsperday" in body_low
        or "free_tier_requests" in body_low
        or "limit: 20" in body_low
        or "requests per day" in body_low
        or "tokens per day" in body_low
        or "neurons" in body_low
        or "limit: 10000" in body_low
        or bool(re.search(r"\b(rpd|tpd)\b", body_low))
        or ("daily" in body_low and "quota" in body_low)
        or ("daily" in body_low and "limit" in body_low)
    )

    now = datetime.now(timezone.utc)

    # Check for duration string in body: "retry in 1h 2m 3s" or "try again in 14h23m10s"
    m = re.search(r"(?:retry|try again) in (?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+(?:\.\d+)?)s)?", body, re.IGNORECASE)
    if m and any((m.group(1), m.group(2), m.group(3))):
        h = int(m.group(1) or 0)
        mins = int(m.group(2) or 0)
        s = float(m.group(3) or 0)
        total_sec = h * 3600 + mins * 60 + s
        if total_sec >= 60:
            reset_dt = now + timedelta(seconds=total_sec)
            reason = f"{provider} API quota exhausted. Retry required in {total_sec:.0f}s ({h}h {mins}m {s:.0f}s)."
            return True, reset_dt, reason
        elif not has_daily_metric:
            return False, None, ""

    # Check Retry-After header
    if err.headers:
        ra = err.headers.get("Retry-After")
        if ra:
            try:
                ra_sec = float(ra)
                if ra_sec >= 60:
                    reset_dt = now + timedelta(seconds=ra_sec)
                    return True, reset_dt, f"{provider} API Retry-After cooldown: {ra_sec:.0f}s."
                elif not has_daily_metric:
                    return False, None, ""
            except ValueError:
                pass

    if has_daily_metric:
        # Default daily reset is next 00:00 UTC (Midnight UTC)
        reset_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        reason = f"{provider} Free Tier daily quota exhausted. Resets at 00:00 UTC."
        return True, reset_dt, reason

    return False, None, ""


def infer_provider(cd: dict) -> str:
    """Infer the provider ('cloudflare', 'groq', 'gemini' or 'all') from a cooldown dictionary."""
    if not isinstance(cd, dict):
        return "all"
    p = str(cd.get("provider", "")).strip().lower()
    if p in ("cloudflare", "groq", "gemini"):
        return p
    reason = str(cd.get("reason", "")).lower()
    if any(k in reason for k in ("cloudflare", "workers ai", "neuron", "glm", "zai-org")):
        return "cloudflare"
    if any(k in reason for k in ("groq", "llama", "gpt-oss", "rpd", "tpd")):
        return "groq"
    if any(k in reason for k in ("gemini", "goog", "google")):
        return "gemini"
    return "all"


def load_history(history_path: Path = HISTORY_PATH, strict: bool = False) -> dict:
    """Load history.json structure.

    If strict=True, raises FileNotFoundError if history file does not exist.
    Raises json.JSONDecodeError or ValueError if history file exists but is unreadable or malformed.
    """
    p = Path(history_path)
    if not p.is_file():
        if strict:
            raise FileNotFoundError(f"History file not found: {history_path}")
        return {"posted": [], "processed": [], "classified_pool": [], "quota_cooldown": {}, "quota_cooldowns": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"History file root is not a JSON object: {type(data)}")
    if "classified_pool" not in data:
        data["classified_pool"] = []
    if "quota_cooldown" not in data:
        data["quota_cooldown"] = {}
    if "quota_cooldowns" not in data or not isinstance(data["quota_cooldowns"], dict):
        data["quota_cooldowns"] = {}
    return data


def save_history(data: dict, history_path: Path = HISTORY_PATH) -> None:
    """Save history.json with indentation."""
    p = Path(history_path)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_quota_cooldown(history_path: Path = HISTORY_PATH, provider: str | None = None) -> dict:
    """Returns active cooldown info for the specified provider if currently in cooldown, else empty dict.

    If provider is specified ('groq' or 'gemini'), checks cooldown for that provider.
    If provider is None:
      - Resolves active provider from environment/ai_provider.
      - If active provider is known, checks that provider's cooldown.
      - If no active provider is known, checks legacy quota_cooldown.
    """
    data = load_history(history_path)
    now = datetime.now(timezone.utc)

    target_prov = provider.strip().lower() if provider else None
    if not target_prov:
        try:
            from ai_provider import get_active_provider
            active = get_active_provider()
            if active:
                target_prov = active
        except ImportError:
            pass
        if not target_prov:
            if os.environ.get("CLOUDFLARE_API_TOKEN", "").strip() and os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip():
                target_prov = "cloudflare"
            elif os.environ.get("GROQ_API_KEY", "").strip():
                target_prov = "groq"
            elif os.environ.get("GEMINI_API_KEY", "").strip():
                target_prov = "gemini"

    # 1. Check provider-specific entry in quota_cooldowns if target_prov is known
    cooldowns = data.get("quota_cooldowns", {})
    if isinstance(cooldowns, dict) and target_prov and target_prov in cooldowns:
        cd = cooldowns[target_prov]
        if isinstance(cd, dict) and cd.get("active"):
            resets_at_str = cd.get("resets_at")
            if resets_at_str:
                try:
                    resets_at = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
                    if now < resets_at:
                        return cd
                    # Expired: clear active state
                    cd["active"] = False
                    save_history(data, history_path)
                    return {}
                except Exception:
                    pass

    # 2. Check legacy quota_cooldown
    cd_legacy = data.get("quota_cooldown", {})
    if isinstance(cd_legacy, dict) and cd_legacy.get("active"):
        resets_at_str = cd_legacy.get("resets_at")
        if resets_at_str:
            try:
                resets_at = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
                if now < resets_at:
                    legacy_prov = infer_provider(cd_legacy)
                    if target_prov:
                        if legacy_prov in (target_prov, "all", "unknown"):
                            return cd_legacy
                        # Legacy cooldown belongs to a different provider
                        return {}
                    return cd_legacy
                # Expired
                cd_legacy["active"] = False
                save_history(data, history_path)
                return {}
            except Exception:
                pass

    return {}


def is_cooldown_active(history_path: Path = HISTORY_PATH, provider: str | None = None) -> bool:
    """Check whether an API quota cooldown is currently active for the provider."""
    return bool(get_quota_cooldown(history_path, provider=provider))


def get_all_quota_cooldowns(history_path: Path = HISTORY_PATH) -> dict[str, dict]:
    """Return a mapping of provider -> active cooldown dict for all providers with active cooldowns."""
    active_map = {}
    for prov in ("cloudflare", "groq", "gemini"):
        cd = get_quota_cooldown(history_path, provider=prov)
        if cd and cd.get("active"):
            active_map[prov] = cd
    return active_map


def are_all_configured_providers_cooling_down(
    history_path: Path = HISTORY_PATH,
    configured_providers: list[str] | None = None
) -> tuple[bool, str, datetime | None]:
    """Check if ALL configured free AI providers are currently in active quota cooldown.

    Returns:
        (all_cooling_down: bool, reason_message: str, earliest_resets_at: datetime | None)
    """
    # 1. First check if a generic or legacy cooldown is active in history.json
    cd_legacy = get_quota_cooldown(history_path, provider=None)
    if cd_legacy and cd_legacy.get("active"):
        resets_at_str = cd_legacy.get("resets_at")
        dt = None
        if resets_at_str:
            try:
                dt = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
            except Exception:
                pass
        reason = cd_legacy.get("reason", "Daily quota exhausted")

        if configured_providers is None:
            try:
                from ai_provider import get_configured_providers
                configured_providers = get_configured_providers()
            except ImportError:
                configured_providers = []

        if not configured_providers or len(configured_providers) <= 1:
            return True, reason, dt

    if configured_providers is None:
        try:
            from ai_provider import get_configured_providers
            configured_providers = get_configured_providers()
        except ImportError:
            configured_providers = []

    if not configured_providers:
        if cd_legacy and cd_legacy.get("active"):
            resets_at_str = cd_legacy.get("resets_at")
            dt = None
            if resets_at_str:
                try:
                    dt = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
                except Exception:
                    pass
            return True, cd_legacy.get("reason", "Daily quota exhausted"), dt
        return False, "No AI providers configured", None

    active_cooldowns = {}
    reset_times = []
    for prov in configured_providers:
        cd = get_quota_cooldown(history_path, provider=prov)
        if cd and cd.get("active"):
            active_cooldowns[prov] = cd
            resets_at_str = cd.get("resets_at")
            if resets_at_str:
                try:
                    dt = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
                    reset_times.append(dt)
                except Exception:
                    pass

    # If all configured providers have active cooldowns
    if len(active_cooldowns) == len(configured_providers):
        earliest_reset = min(reset_times) if reset_times else None
        prov_names = ", ".join(p.upper() for p in configured_providers)
        msg = f"All configured AI providers ({prov_names}) are in active quota cooldown"
        return True, msg, earliest_reset

    available = [p for p in configured_providers if p not in active_cooldowns]
    return False, f"Available providers exist: {', '.join(available)}", None


def get_token_metadata(history_path: Path = HISTORY_PATH) -> dict:
    """Return non-sensitive Instagram token metadata from history.json."""
    data = load_history(history_path)
    meta = data.get("token_metadata", {})
    return meta if isinstance(meta, dict) else {}


def set_token_metadata(metadata: dict, history_path: Path = HISTORY_PATH) -> None:
    """Persist non-sensitive Instagram token metadata into history.json."""
    data = load_history(history_path)
    clean_meta = {k: v for k, v in metadata.items() if ("token" not in k.lower() or k == "token_type")}
    clean_meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["token_metadata"] = clean_meta
    save_history(data, history_path)


def set_quota_cooldown(
    resets_at: datetime,
    reason: str,
    history_path: Path = HISTORY_PATH,
    provider: str | None = None
) -> None:
    """Set an active quota cooldown in history.json for a provider."""
    data = load_history(history_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    prov = (provider or "").strip().lower()
    if not prov:
        prov = infer_provider({"reason": reason})

    cooldown_entry = {
        "active": True,
        "resets_at": resets_at.isoformat(),
        "reason": reason,
        "provider": prov,
        "updated_at": now_iso,
    }

    if "quota_cooldowns" not in data or not isinstance(data["quota_cooldowns"], dict):
        data["quota_cooldowns"] = {}

    if prov in ("cloudflare", "groq", "gemini"):
        data["quota_cooldowns"][prov] = cooldown_entry
    else:
        data["quota_cooldowns"]["cloudflare"] = cooldown_entry
        data["quota_cooldowns"]["groq"] = cooldown_entry
        data["quota_cooldowns"]["gemini"] = cooldown_entry

    data["quota_cooldown"] = cooldown_entry
    save_history(data, history_path)


def clear_quota_cooldown(history_path: Path = HISTORY_PATH, provider: str | None = None) -> None:
    """Clear active quota cooldown in history.json for a provider or all providers."""
    data = load_history(history_path)
    target_prov = (provider or "").strip().lower()

    changed = False
    if target_prov:
        if "quota_cooldowns" in data and isinstance(data["quota_cooldowns"], dict):
            if target_prov in data["quota_cooldowns"] and data["quota_cooldowns"][target_prov].get("active"):
                data["quota_cooldowns"][target_prov]["active"] = False
                changed = True
        if "quota_cooldown" in data and isinstance(data["quota_cooldown"], dict):
            if infer_provider(data["quota_cooldown"]) == target_prov and data["quota_cooldown"].get("active"):
                data["quota_cooldown"]["active"] = False
                changed = True
    else:
        if "quota_cooldown" in data and isinstance(data["quota_cooldown"], dict) and data["quota_cooldown"].get("active"):
            data["quota_cooldown"]["active"] = False
            changed = True
        if "quota_cooldowns" in data and isinstance(data["quota_cooldowns"], dict):
            for k in data["quota_cooldowns"]:
                if data["quota_cooldowns"][k].get("active"):
                    data["quota_cooldowns"][k]["active"] = False
                    changed = True

    if changed:
        save_history(data, history_path)


DEFAULT_CADENCE_MINUTES = float(os.environ.get("PUBLISH_CADENCE_MINUTES", "25"))
DEFAULT_MAX_ROLLING_POSTS_24H = int(os.environ.get("MAX_ROLLING_POSTS_24H", "50"))


def get_rolling_24h_published_posts(history_path: Path = HISTORY_PATH, now: datetime | None = None) -> list:
    """Return all confirmed published posts within the rolling 24-hour window (86,400s).

    Only entries with published=True and a valid non-empty media_id are counted.
    Failed attempts, dry-run entries, or missing media IDs are strictly excluded.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    data = load_history(history_path)
    confirmed = []
    for entry in data.get("posted", []):
        if not entry.get("published"):
            continue
        if not entry.get("media_id"):
            continue
        ts_str = entry.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                confirmed.append(entry)
        except Exception:
            continue
    return confirmed


def get_last_successful_publication_time(history_path: Path = HISTORY_PATH) -> datetime | None:
    """Return the datetime of the most recent confirmed published post, or None if none exist."""
    data = load_history(history_path)
    latest_ts = None
    for entry in data.get("posted", []):
        if not entry.get("published") or not entry.get("media_id"):
            continue
        ts_str = entry.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
        except Exception:
            continue
    return latest_ts


def check_publication_cadence_due(
    history_path: Path = HISTORY_PATH,
    cadence_minutes: float = DEFAULT_CADENCE_MINUTES,
    now: datetime | None = None
) -> tuple[bool, float, float]:
    """Check if enough time has elapsed since the last confirmed publication.

    Enforces minimum confirmed Instagram publication cadence of exactly cadence_minutes.

    Returns:
        (is_due, elapsed_minutes, remaining_minutes_until_due)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    last_pub = get_last_successful_publication_time(history_path)
    if last_pub is None:
        return True, 999999.0, 0.0

    elapsed_sec = (now - last_pub).total_seconds()
    elapsed_min = max(0.0, elapsed_sec / 60.0)
    # Strictly enforce minimum confirmed publication cadence
    if elapsed_min >= cadence_minutes:
        return True, elapsed_min, 0.0
    remaining_min = max(0.0, cadence_minutes - elapsed_min)
    return False, elapsed_min, remaining_min


def check_rolling_24h_cap(
    history_path: Path = HISTORY_PATH,
    max_posts: int = DEFAULT_MAX_ROLLING_POSTS_24H,
    now: datetime | None = None
) -> tuple[bool, int, int]:
    """Check whether the rolling 24-hour confirmed publication count is strictly under the cap.

    Returns:
        (is_under_cap, current_confirmed_count, remaining_allowance)
    """
    confirmed = get_rolling_24h_published_posts(history_path, now=now)
    count = len(confirmed)
    is_under = count < max_posts
    remaining = max(0, max_posts - count)
    return is_under, count, remaining


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

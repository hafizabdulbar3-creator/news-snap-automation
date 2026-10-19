"""NEWS SNAP Multi-Provider AI Client.

Provides a unified interface for hosted text generation and article triage:
1. Groq API (Primary):
   - Endpoint: https://api.groq.com/openai/v1/chat/completions
   - Configured via GROQ_API_KEY
   - Supported models: llama-3.3-70b-versatile (default), llama-3.1-8b-instant
2. Gemini API (Secondary / Fallback):
   - Endpoint: https://generativelanguage.googleapis.com/v1beta/models
   - Configured via GEMINI_API_KEY
   - Supported models: gemini-3.8-flash (default), gemini-2.0-flash

Features:
- Automatic provider detection (prefers Groq if GROQ_API_KEY is present).
- Strict secret sanitization in logs and exception messages.
- Bounded retries with exponential backoff and Retry-After header parsing.
- Fail-closed behavior in production if required keys are missing or invalid.
- Deterministic mock generation only in local test mode (marked synthetic).
"""

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Groq Defaults
DEFAULT_GROQ_API_BASE = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

# Gemini Defaults
DEFAULT_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def is_production_mode() -> bool:
    """Return True if running in production or CI automation mode."""
    return (
        os.environ.get("GITHUB_ACTIONS") == "true"
        or os.environ.get("CI") == "true"
        or os.environ.get("NEWS_SNAP_PROD") == "1"
    )


def sanitize_ai_error(err: Exception | str) -> str:
    """Sanitize error messages to prevent leaking API keys or secrets in logs."""
    msg = str(err)
    for env_var in ("GROQ_API_KEY", "GEMINI_API_KEY", "INSTAGRAM_ACCESS_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(env_var, "")
        if val and len(val) > 4:
            msg = msg.replace(val, f"[REDACTED_{env_var}]")
    # Redact common key patterns
    msg = re.sub(r"gsk_[a-zA-Z0-9_\-]+", "[REDACTED_GROQ_KEY]", msg)
    msg = re.sub(r"key=[a-zA-Z0-9_\-]+", "key=[REDACTED]", msg)
    msg = re.sub(r"Bearer\s+[a-zA-Z0-9_\-]+", "Bearer [REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"x-goog-api-key['\":\s]+[a-zA-Z0-9_\-]+", "x-goog-api-key: [REDACTED]", msg, flags=re.IGNORECASE)
    return msg


def get_active_provider() -> str:
    """Determine the active AI provider based on environment variables.

    Priority:
    1. Explicit AI_PROVIDER env var ("groq" or "gemini")
    2. GROQ_API_KEY present -> "groq"
    3. GEMINI_API_KEY present -> "gemini"
    4. Empty string if no provider configured
    """
    explicit = os.environ.get("AI_PROVIDER", "").strip().lower()
    if explicit in ("groq", "gemini"):
        return explicit

    if os.environ.get("GROQ_API_KEY", "").strip():
        return "groq"
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"

    return ""


def call_groq_chat_completion(
    prompt: str,
    system_prompt: str = "",
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1000,
    max_attempts: int = 3,
    api_base: str | None = None
) -> dict:
    """Execute a chat completion request to Groq API with bounded retries."""
    key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise ValueError("GROQ_API_KEY is not configured.")

    base = api_base or os.environ.get("GROQ_API_BASE", DEFAULT_GROQ_API_BASE).rstrip("/")
    url = f"{base}/chat/completions"
    model_name = model or os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"}
    }
    req_body = json.dumps(payload).encode("utf-8")

    last_error = None
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            data=req_body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "NEWS-SNAP-automation/1.0"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_text = resp.read().decode("utf-8")
                resp_data = json.loads(resp_text)

            choices = resp_data.get("choices", [])
            if not choices:
                raise ValueError("Groq returned empty choices in completion response.")

            content = choices[0].get("message", {}).get("content", "")
            if not content:
                raise ValueError("Groq returned empty content in message.")

            # Clean markdown code fences if present
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)

            parsed = json.loads(cleaned)
            return parsed

        except urllib.error.HTTPError as e:
            last_error = e
            sanitized = sanitize_ai_error(e)

            # HTTP 401 Unauthorized -> Non-retryable
            if e.code == 401:
                print(f"[ERROR] Groq API authentication failed (HTTP 401): {sanitized}")
                raise RuntimeError(f"Groq API authentication failed (HTTP 401): {sanitized}") from e

            # HTTP 429 Rate Limit / Quota Exceeded
            if e.code == 429:
                # Check for Retry-After header
                ra_header = e.headers.get("Retry-After") if e.headers else None
                retry_after = None
                if ra_header:
                    try:
                        retry_after = float(ra_header)
                    except ValueError:
                        pass

                # Check body for daily quota indicators
                try:
                    from quota_manager import parse_quota_cooldown, set_quota_cooldown
                    is_exhausted, reset_dt, reason = parse_quota_cooldown(e)
                    if is_exhausted and reset_dt:
                        history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
                        print(f"[GROQ QUOTA EXHAUSTED] {reason} (Cooldown until {reset_dt.isoformat()}).")
                        try:
                            set_quota_cooldown(reset_dt, reason, history_path)
                        except Exception:
                            pass
                        raise RuntimeError(f"Groq API quota exhausted: {reason}") from e
                except ImportError:
                    pass

                if attempt < max_attempts:
                    delay = min(retry_after or (2.0 ** attempt), 25.0)
                    print(f"[RETRY] Groq HTTP 429 on attempt {attempt}/{max_attempts}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
                else:
                    raise RuntimeError(f"Groq API rate limit exceeded after {max_attempts} attempts: {sanitized}") from e

            # Server error 5xx -> Retryable
            if 500 <= e.code < 600 and attempt < max_attempts:
                delay = 2.0 * (2 ** (attempt - 1)) + random.uniform(0.5, 1.5)
                print(f"[RETRY] Groq server error HTTP {e.code} on attempt {attempt}/{max_attempts}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                continue

            raise RuntimeError(f"Groq API permanent failure (HTTP {e.code}): {sanitized}") from e

        except json.JSONDecodeError as e:
            last_error = e
            print(f"[WARN] Groq response was not valid JSON on attempt {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                time.sleep(1.0)
                continue
            raise RuntimeError(f"Groq output could not be parsed as valid JSON: {e}") from e

        except Exception as e:
            last_error = e
            sanitized = sanitize_ai_error(e)
            if attempt < max_attempts:
                delay = 2.0 ** attempt
                print(f"[RETRY] Transient Groq error on attempt {attempt}/{max_attempts}: {sanitized}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                continue
            raise RuntimeError(f"Groq API failed after {max_attempts} attempts: {sanitized}") from e

    raise RuntimeError(f"Groq API failed: {sanitize_ai_error(last_error)}")


def call_gemini_generate_content(
    prompt: str,
    system_prompt: str = "",
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
    max_attempts: int = 4,
    api_base: str | None = None
) -> dict:
    """Execute a content generation request to Gemini REST API with bounded retries."""
    key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    base = api_base or os.environ.get("GEMINI_API_BASE", DEFAULT_GEMINI_API_BASE).rstrip("/")
    model_name = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = f"{base}/{model_name}:generateContent?key={key}"

    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    payload = {
        "contents": [
            {
                "parts": [{"text": full_prompt}]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": temperature
        }
    }
    req_body = json.dumps(payload).encode("utf-8")

    last_error = None
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            data=req_body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                resp_text = resp.read().decode("utf-8")
                resp_data = json.loads(resp_text)

            candidates = resp_data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned empty candidates.")

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ValueError("Gemini returned empty parts in candidate.")

            text = parts[0].get("text", "")
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)

            parsed = json.loads(cleaned)
            return parsed

        except urllib.error.HTTPError as e:
            last_error = e
            sanitized = sanitize_ai_error(e)

            if e.code == 429:
                try:
                    from quota_manager import parse_quota_cooldown, set_quota_cooldown
                    is_exhausted, reset_dt, reason = parse_quota_cooldown(e)
                    if is_exhausted and reset_dt:
                        history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
                        print(f"[GEMINI QUOTA EXHAUSTED] {reason} (Cooldown until {reset_dt.isoformat()}).")
                        try:
                            set_quota_cooldown(reset_dt, reason, history_path)
                        except Exception:
                            pass
                        raise RuntimeError(f"Gemini API quota exhausted: {reason}") from e
                except ImportError:
                    pass

                if attempt < max_attempts:
                    delay = min(2.0 ** attempt, 25.0)
                    print(f"[RETRY] Gemini HTTP 429 on attempt {attempt}/{max_attempts}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Gemini API rate limit exceeded: {sanitized}") from e

            if attempt < max_attempts and 500 <= e.code < 600:
                delay = 2.0 ** attempt
                time.sleep(delay)
                continue

            raise RuntimeError(f"Gemini API permanent failure (HTTP {e.code}): {sanitized}") from e

        except Exception as e:
            last_error = e
            sanitized = sanitize_ai_error(e)
            if attempt < max_attempts:
                time.sleep(2.0 ** attempt)
                continue
            raise RuntimeError(f"Gemini API failed after {max_attempts} attempts: {sanitized}") from e

    raise RuntimeError(f"Gemini API failed: {sanitize_ai_error(last_error)}")


def classify_articles_ai(articles: list[dict]) -> dict:
    """Classify a batch of news articles using the active AI provider (Groq or Gemini)."""
    provider = get_active_provider()
    is_prod = is_production_mode()

    if not provider:
        if is_prod:
            raise RuntimeError(
                "CRITICAL: Neither GROQ_API_KEY nor GEMINI_API_KEY is configured in production environment. "
                "Refusing to proceed without a verified AI provider."
            )
        # Local offline test fallback
        results = []
        for i, a in enumerate(articles, start=1):
            results.append({
                "id": i,
                "importance": "MAJOR" if i <= 3 else "NORMAL",
                "topic": "World News",
                "reason": "Offline test evaluation fallback."
            })
        return {"results": results, "source": "offline_mock"}

    items = [
        {"id": i, "title": a["title"], "source": a.get("domain", "")}
        for i, a in enumerate(articles, start=1)
    ]

    system_prompt = (
        "You are the senior news-triage AI for NEWS SNAP. "
        "Your task is to classify news articles and return ONLY a valid JSON object matching the requested schema. "
        "Do not include any conversational text or markdown formatting outside the JSON."
    )

    user_prompt = """Classify every article below. DO NOT omit any article from the results.

Requirements:
1. Language: Must be natural English. If foreign or nonsensical, mark as LOW with topic "Non-English".
2. Quality filter:
   - Mark as MAJOR: Major geopolitical events, wars, summits, national elections, central bank actions, major scientific/tech breakthroughs, major disasters, or stories of broad international consequence.
   - Mark as NORMAL: Legitimate national/regional policy, economic trends, corporate milestones, or notable public interest stories.
   - Mark as LOW: Local disputes, gossip, obituaries, sports-only, entertainment trivia, sensationalist claims, or unverified rumors.

Return ONLY valid JSON with this exact structure:
{
  "results": [
    {
      "id": 1,
      "importance": "MAJOR",
      "topic": "World News",
      "reason": "Clear explanation of public significance."
    }
  ]
}

Articles to classify:
""" + json.dumps(items, ensure_ascii=False)

    print(f"[AI TRIAGE] Routing classification of {len(articles)} articles to provider: {provider.upper()}")
    if provider == "groq":
        return call_groq_chat_completion(prompt=user_prompt, system_prompt=system_prompt)
    else:
        return call_gemini_generate_content(prompt=user_prompt, system_prompt=system_prompt)


def generate_post_content_ai(article: dict, source_evidence: str = "") -> dict:
    """Generate headline, curiosity line, caption and hashtags using the active AI provider."""
    provider = get_active_provider()
    is_prod = is_production_mode()

    if not provider:
        if is_prod:
            raise RuntimeError(
                "CRITICAL: Neither GROQ_API_KEY nor GEMINI_API_KEY is configured in production environment. "
                "Refusing to generate or publish synthetic news content."
            )
        # In offline local mode, caller should invoke generate_mock_post
        raise ValueError("No AI provider key configured.")

    source = str(article.get("domain", "")).strip()
    url = str(article.get("url", "")).strip()
    title = str(article.get("title", "")).strip()

    context_clause = ""
    if source_evidence:
        context_clause = f"\nVerified source context/excerpt:\n\"\"\"{source_evidence[:1500]}\"\"\"\n"

    system_prompt = (
        "You are the senior editor for NEWS SNAP. "
        "Your job is to transform this news report into a high-impact, 100% accurate, professional NEWS SNAP Instagram post. "
        "Return ONLY a valid JSON object matching the requested schema."
    )

    user_prompt = f"""Source article:
Headline: "{title}"
Source publication: {source}
Original URL: {url}
{context_clause}
STRICT REQUIREMENTS:
1. Headline: 4–14 words. Punchy, clear, journalistic, factual. NEVER cut off mid-thought.
2. Curiosity line: 3–10 words. Summarizes significance or impact.
3. Caption: 20–80 words. Strictly factual summary of the news. Do NOT extrapolate or hallucinate facts.
4. Hashtags: 3–6 hashtags, must include "#NewsSnap".
5. Language: Natural, publication-ready English.

Return ONLY a valid JSON object with these exact keys:
{{
  "headline": "...",
  "curiosity_line": "...",
  "caption": "...",
  "hashtags": ["#NewsSnap", "#..."]
}}
"""

    print(f"[AI GENERATOR] Routing post generation for '{title[:45]}...' to provider: {provider.upper()}")
    if provider == "groq":
        return call_groq_chat_completion(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=600
        )
    else:
        return call_gemini_generate_content(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2
        )

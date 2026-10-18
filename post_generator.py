import html
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException
    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

# Primary supported Gemini API model (Default to gemini-3.8-flash)
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class SourceEvidenceParser(HTMLParser):
    """Fast HTML parser to extract og:description, meta description, JSON-LD, or lead paragraphs."""
    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self.meta_desc = ""
        self.paragraphs = []
        self._current_tag = None
        self._p_buf = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        self._current_tag = t
        if t == "meta":
            attrs_dict = {k.lower(): v for k, v in attrs if k and v}
            prop = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            if prop in ("og:description", "description", "twitter:description", "article:description"):
                content = attrs_dict.get("content", "").strip()
                if len(content) > len(self.meta_desc):
                    self.meta_desc = html.unescape(content)
        elif t == "p":
            self._p_buf = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "p" and self._p_buf:
            text = re.sub(r"\s+", " ", html.unescape("".join(self._p_buf))).strip()
            if len(text) >= 35:
                self.paragraphs.append(text)
            self._p_buf = []
        self._current_tag = None

    def handle_data(self, data):
        if self._current_tag == "p":
            self._p_buf.append(data)


def fetch_article_summary(url: str, timeout: int = 6) -> str:
    """Attempt to fetch the meta description or lead paragraphs from the source article for grounded facts."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NEWS-SNAP/1.0",
                "Accept": "text/html,application/xhtml+xml",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(384 * 1024)  # Read first 384KB
            charset = response.headers.get_content_charset() or "utf-8"
            html_text = raw.decode(charset, errors="replace")

        parser = SourceEvidenceParser()
        parser.feed(html_text)
        desc = re.sub(r"\s+", " ", parser.meta_desc).strip()
        if len(desc) >= 30:
            return desc
        if parser.paragraphs:
            return " ".join(parser.paragraphs[:2])[:600]
    except Exception:
        pass
    return ""


def is_latin_script(text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    for char in text:
        if char.isalpha():
            name = unicodedata.name(char, "")
            if not name.startswith("LATIN "):
                return False
        elif char.isdigit() and not char.isascii():
            return False
    return True


def is_english(text: str, minimum_confidence: float = 0.60) -> bool:
    if not is_latin_script(text):
        return False

    norm_text = text.lower()
    tokens = re.findall(r"[a-z]+", norm_text)
    if len(tokens) < 2:
        return False

    if LANGDETECT_AVAILABLE:
        try:
            results = detect_langs(norm_text)
            if results and results[0].lang == "en" and results[0].prob >= minimum_confidence:
                return True
        except LangDetectException:
            pass

    # Heuristic fallback
    common_english = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "it",
        "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
        "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
        "an", "will", "my", "one", "all", "would", "there", "their", "what",
        "so", "up", "out", "if", "about", "who", "which", "when", "can",
        "into", "year", "your", "could", "them", "other", "than", "then",
        "now", "its", "over", "also", "after", "two", "how", "our", "new",
        "most", "us", "says", "said", "reported", "officials", "state",
        "court", "global", "trade", "world", "key", "report", "impact",
        "news", "first", "more", "over", "under", "deal", "plan", "sanctions"
    }
    matches = sum(1 for t in tokens if t in common_english)
    return matches >= 1


def is_mock_fixture_article(article: dict) -> bool:
    """Determine whether an article is a local unit-test / mock fixture or a genuine source report."""
    if not isinstance(article, dict):
        return True
    url = str(article.get("url", "")).strip().lower()
    domain = str(article.get("domain", "")).strip().lower()
    title = str(article.get("title", "")).strip()

    if not url or not domain or not title:
        return True

    mock_domains = {"example.com", "example.org", "test.com", "mock.com", "localhost"}
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if domain in mock_domains or hostname in mock_domains or hostname.endswith(".example.com"):
        return True
    if any(url.startswith(p) for p in ("https://example.com", "http://example.com", "mock://")):
        return True
    if re.search(r"\b(test fixture|mock story|dummy article|unit test)\b", title, re.IGNORECASE):
        return True
    return False


def word_count(text: str) -> int:
    return len(text.split())


def extract_numeric_tokens(text: str) -> set[str]:
    """Extract standalone numbers, monetary values, and percentages."""
    cleaned = re.sub(r"[,']", "", text)
    tokens = re.findall(r"\b\$?\d+(?:\.\d+)?%?(?:[kKmMbBtT]|(?:\s*(?:million|billion|trillion|percent)))?\b", cleaned, re.IGNORECASE)
    norm = set()
    for t in tokens:
        clean_t = t.lower().replace("$", "").replace("%", "").strip()
        if clean_t.isdigit() and len(clean_t) == 4 and 1990 <= int(clean_t) <= 2030:
            continue
        if clean_t:
            norm.add(clean_t)
    return norm


def validate_factual_grounding(post: dict, article: dict, source_evidence: str = "") -> None:
    """Ensure generated headline, summary, and caption do not introduce unsupported claims,
    invented numbers, or convert speculative allegations into established facts.
    """
    if not isinstance(post, dict) or not isinstance(article, dict):
        return

    headline = str(post.get("headline", "")).strip()
    caption = str(post.get("caption", "")).strip()
    art_title = str(article.get("title", "")).strip()

    # 1. Speculation / Allegation Safeguard
    uncertainty_cues = (
        "?", "alleged", "allegedly", "alleges", "allegation", "allegations", "suspected", "may face",
        "could face", "might face", "claims", "reportedly", "investigating",
        "under probe", "accused of"
    )
    title_has_uncertainty = any(cue in art_title.lower() for cue in uncertainty_cues)
    if title_has_uncertainty:
        attribution_markers = (
            "alleged", "allegedly", "claims", "reportedly", "suspected", "may",
            "could", "probe", "investigation", "says", "stated", "accused",
            "according to", "facing", "under", "warns", "reports"
        )
        headline_lower = headline.lower()
        if not any(marker in headline_lower or marker in caption.lower() for marker in attribution_markers):
            raise ValueError(
                f"FACTUAL GROUNDING REFUSAL: Source title contains uncertainty/allegation ('{art_title}'), "
                f"but generated post converts it to an established fact without attribution."
            )

    # 2. Number / Quantity Grounding
    headline_nums = extract_numeric_tokens(headline)
    source_nums = extract_numeric_tokens(f"{art_title} {source_evidence}")
    unsupported_nums = [n for n in headline_nums if n not in source_nums]
    if unsupported_nums:
        raise ValueError(
            f"FACTUAL GROUNDING REFUSAL: Headline contains unsupported number(s) {unsupported_nums} "
            f"not substantiated in source headline or retrieved evidence."
        )

    # 3. Sensational Clickbait Fabrication Check
    sensational_terms = (
        "bombshell", "shocking truth", "mind-blowing", "unbelievable",
        "you won't believe", "miracle cure", "secret plot revealed"
    )
    if any(s in headline.lower() for s in sensational_terms):
        raise ValueError("FACTUAL GROUNDING REFUSAL: Headline contains sensationalized clickbait fabrication.")


def validate_post(post: dict, source: str, url: str, is_mock: bool = False, article: dict = None, source_evidence: str = "") -> dict:
    if not isinstance(post, dict):
        raise ValueError("Output must be a JSON object.")

    required = {"headline", "curiosity_line", "caption", "hashtags"}
    if not required.issubset(post):
        raise ValueError("Required post fields are missing.")

    headline = str(post.get("headline", "")).strip()
    curiosity = str(post.get("curiosity_line", "")).strip()
    caption = str(post.get("caption", "")).strip()

    for field, value in (("headline", headline), ("curiosity_line", curiosity), ("caption", caption)):
        if not value:
            raise ValueError(f"{field} is missing.")
        if not is_latin_script(value):
            raise ValueError(f"{field} contains non-Latin text.")
        if not is_english(value):
            raise ValueError(f"{field} failed English validation.")

    # Remove quotes around headline if generated
    headline = headline.strip("\"' ")
    curiosity = curiosity.strip("\"' ")

    # Gracefully normalize minor word count deviations from LLM
    hl_words = headline.split()
    if len(hl_words) > 14:
        hl_words = hl_words[:14]
        while len(hl_words) > 4 and hl_words[-1].lower() in {
            "by", "to", "at", "of", "for", "on", "with", "and", "or", "a", "an", "the", "from", "as", "in"
        }:
            hl_words = hl_words[:-1]
        headline = " ".join(hl_words)

    if not 4 <= word_count(headline) <= 14:
        raise ValueError(f"Headline must contain 4–14 words, got {word_count(headline)}.")

    c_words = curiosity.split()
    if len(c_words) > 10:
        curiosity = " ".join(c_words[:10])
    elif len(c_words) < 3:
        curiosity = f"{curiosity} - Global Update"

    if not 3 <= word_count(curiosity) <= 10:
        raise ValueError(f"Curiosity line must contain 3–10 words, got {word_count(curiosity)}.")

    cap_words = caption.split()
    if len(cap_words) > 80:
        caption = " ".join(cap_words[:78]) + "..."

    if not 20 <= word_count(caption) <= 80:
        raise ValueError(f"Caption must contain 20–80 words, got {word_count(caption)}.")

    hashtags = post.get("hashtags", [])
    if not isinstance(hashtags, list) or not 3 <= len(hashtags) <= 6:
        raise ValueError("Provide 3–6 hashtags.")

    cleaned_hashtags = []
    for tag in hashtags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if not tag.startswith("#"):
            tag = f"#{tag}"
        if re.fullmatch(r"#[A-Za-z][A-Za-z0-9_]{1,29}", tag):
            cleaned_hashtags.append(tag)

    if not any(tag.lower() == "#newssnap" for tag in cleaned_hashtags):
        cleaned_hashtags.insert(0, "#NewsSnap")

    # De-duplicate case-insensitively
    seen = set()
    final_hashtags = []
    for tag in cleaned_hashtags:
        low = tag.lower()
        if low not in seen:
            seen.add(low)
            final_hashtags.append(tag)

    # Format complete Instagram caption with source and link
    final_caption = (
        f"{caption}\n\n"
        f"Source: {source}\n"
        f"Original report: {url}\n\n"
        f"{' '.join(final_hashtags)}"
    )

    if len(final_caption) > 2200:
        raise ValueError("Caption exceeds Instagram limit of 2,200 characters.")

    # Clean trailing punctuation from headline
    headline = re.sub(r"[;:,|–—\-]+$", "", headline).strip()

    res = {
        "headline": headline,
        "curiosity_line": curiosity,
        "caption": final_caption,
        "body_summary": caption,
        "hashtags": final_hashtags,
        "is_synthetic": bool(is_mock),
    }

    if article:
        validate_factual_grounding(res, article, source_evidence)

    return res


def generate_mock_post(article: dict) -> dict:
    """Deterministic, high-quality fallback generator for offline unit testing only."""
    title = article.get("title", "").strip()
    source = article.get("domain", "").strip()
    url = article.get("url", "").strip()

    # Clean headline into punchy, complete form (up to 14 words)
    raw_words = title.split()
    if len(raw_words) <= 14:
        headline = " ".join(raw_words)
    else:
        headline_words = raw_words[:14]
        headline = " ".join(headline_words)
        while len(headline.split()) > 4 and headline.split()[-1].lower() in {
            "by", "to", "at", "of", "for", "on", "with", "and", "or", "a", "an", "the", "from", "as"
        }:
            headline = " ".join(headline.split()[:-1])
    headline = re.sub(r"[;:,|–—\-]+$", "", headline).strip()
    curiosity = "Key developments and global impact"
    caption = (
        f"According to reports from {source}, {title}. "
        f"Officials and observers are closely monitoring the developments as the situation unfolds."
    )
    hashtags = ["#NewsSnap", "#WorldNews", "#GlobalReport"]

    res = validate_post({
        "headline": headline,
        "curiosity_line": curiosity,
        "caption": caption,
        "hashtags": hashtags,
    }, source, url, is_mock=True, article=article, source_evidence="")
    res["is_synthetic"] = True
    return res


def is_production_mode() -> bool:
    """Return True if running in production or CI automation mode."""
    return (
        os.environ.get("GITHUB_ACTIONS") == "true"
        or os.environ.get("CI") == "true"
        or os.environ.get("NEWS_SNAP_PROD") == "1"
    )


def sanitize_gemini_error(err: Exception | str) -> str:
    """Sanitize error messages to prevent leaking API keys or secrets in logs."""
    msg = str(err)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key and len(api_key) > 5:
        msg = msg.replace(api_key, "[REDACTED_API_KEY]")
    msg = re.sub(r"key=[a-zA-Z0-9_\-]+", "key=[REDACTED]", msg)
    msg = re.sub(r"x-goog-api-key['\":\s]+[a-zA-Z0-9_\-]+", "x-goog-api-key: [REDACTED]", msg, flags=re.IGNORECASE)
    return msg


def is_retryable_gemini_error(err: Exception) -> tuple[bool, float | None, str]:
    """Classify whether a Gemini API error is transient/retryable or permanent.

    Returns:
        (is_retryable, retry_after_seconds, description)
    """
    if isinstance(err, urllib.error.HTTPError):
        retry_after = None
        if err.headers:
            ra = err.headers.get("Retry-After")
            if ra:
                try:
                    retry_after = float(ra)
                except ValueError:
                    pass

        # Permanent HTTP error codes: Do not retry
        if err.code in (400, 401, 403, 404):
            return False, None, f"Permanent HTTP {err.code}"

        # Transient HTTP error codes: 408, 429, 500, 502, 503, 504
        if err.code in (408, 429, 500, 502, 503, 504):
            try:
                from quota_manager import parse_quota_cooldown, set_quota_cooldown
                is_quota, reset_dt, reason = parse_quota_cooldown(err)
                if is_quota:
                    history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
                    try:
                        set_quota_cooldown(reset_dt, reason, history_path)
                    except Exception:
                        pass
                    return False, None, f"Permanent daily quota exhaustion: {reason}"
            except Exception:
                pass
            return True, retry_after, f"Transient HTTP {err.code}"

        return False, None, f"HTTP {err.code} (non-retryable)"

    if isinstance(err, (urllib.error.URLError, TimeoutError, ConnectionError, OSError)):
        return True, None, f"Transient network/connection error: {type(err).__name__}"

    return False, None, f"Non-retryable error: {type(err).__name__}"


def call_gemini_api(payload: dict, api_key: str, model_name: str = MODEL, max_attempts: int = 4) -> dict:
    """Execute Gemini API call with bounded retries, exponential backoff, jitter, and Retry-After support."""
    api_url = f"{API_BASE}/{model_name}:generateContent"
    req_data = json.dumps(payload).encode("utf-8")
    last_error = None

    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            api_url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.load(response)

            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned empty candidate")

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            if not text:
                raise ValueError("Gemini response contained empty text part")

            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
                text = re.sub(r"\s*```$", "", text)

            post_data = json.loads(text)
            return post_data

        except Exception as e:
            last_error = e
            sanitized = sanitize_gemini_error(e)
            retryable, retry_after, reason = is_retryable_gemini_error(e)

            if not retryable:
                print(f"[ERROR] Non-retryable Gemini error on attempt {attempt}/{max_attempts} ({reason}): {sanitized}")
                raise RuntimeError(f"Gemini API permanent failure: {sanitized}") from e

            if attempt < max_attempts:
                if retry_after is not None and retry_after > 0:
                    delay = min(retry_after, 25.0)
                else:
                    base_delay = 2.0 * (2 ** (attempt - 1))
                    jitter = random.uniform(0.5, 1.5)
                    delay = min(base_delay + jitter, 25.0)

                print(f"[RETRY] Transient Gemini error ({reason}) on attempt {attempt}/{max_attempts}: {sanitized}. Retrying in {delay:.2f}s...")
                time.sleep(delay)
            else:
                print(f"[ERROR] Gemini API retries exhausted ({max_attempts} attempts). Last error: {sanitized}")

    raise RuntimeError(f"Gemini API failed after {max_attempts} attempts. Last error: {sanitize_gemini_error(last_error)}")


def generate_post(article: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    source = str(article.get("domain", "")).strip()
    url = str(article.get("url", "")).strip()
    title = str(article.get("title", "")).strip()

    if not all((title, source, url)):
        raise ValueError("Article title, source or URL is missing.")

    is_prod = is_production_mode()

    try:
        from quota_manager import is_cooldown_active, get_quota_cooldown
        history_path = os.environ.get("NEWS_SNAP_HISTORY_PATH", "history.json")
        if is_cooldown_active(history_path):
            cd = get_quota_cooldown(history_path)
            resets_at = cd.get("resets_at", "scheduled reset")
            reason = cd.get("reason", "Daily quota exhausted")
            raise RuntimeError(
                f"Gemini API quota is currently in active cooldown until {resets_at} ({reason}). "
                f"Refusing to make API requests during active quota cooldown."
            )
    except ImportError:
        pass

    if not api_key:
        if is_prod:
            raise RuntimeError(
                "CRITICAL: GEMINI_API_KEY is missing in production environment. "
                "Refusing to generate or publish synthetic news content."
            )
        print("GEMINI_API_KEY missing in local environment; using verified offline test generator.")
        return generate_mock_post(article)

    # Check if article already carries retrieved source description from preparation step
    source_summary = ""
    if article.get("source_description"):
        source_summary = article["source_description"]
    elif article.get("source_body_excerpt"):
        source_summary = article["source_body_excerpt"]
    else:
        print(f"Fetching source context from {url}...")
        source_summary = fetch_article_summary(url)
        if source_summary:
            print(f"Retrieved source summary ({len(source_summary)} chars).")
        else:
            print("No meta summary retrieved; relying strictly on verified headline.")

    prompt = f"""You are the senior editor for NEWS SNAP.
Your job is to transform this news report into a high-impact, 100% accurate, professional NEWS SNAP Instagram post.

GROUND TRUTH RULES (STRICT):
1. ACCURACY: Only use facts stated in the headline and source summary below. NEVER invent facts, dates, casualty figures, monetary sums, or quotations.
2. PRESERVE UNCERTAINTY: If the report involves an allegation, investigation, or ongoing claim, explicitly attribute it ("officials say", "investigators allege", "according to reports").
3. LANGUAGE: Write natural, fluent English only.

EDITORIAL GUIDELINES:
- headline: Punchy, clear, authoritative headline (5–12 words). Must be compelling and 100% factual.
- curiosity_line: A 3–8 word teaser / sub-kicker giving vital context (e.g. "WHAT THIS MEANS FOR GLOBAL TRADE").
- caption: 25–60 words summarizing the core facts clearly and concisely.
- hashtags: 3–5 relevant tags, including "#NewsSnap".

Source Headline: {title}
Publisher: {source}
Original URL: {url}
Source Summary: {source_summary or 'None provided; use only confirmed headline details.'}

Return ONLY valid JSON matching this schema:
{{
  "headline": "...",
  "curiosity_line": "...",
  "caption": "...",
  "hashtags": ["#NewsSnap", "#TopicTag", "#NewsUpdate"]
}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.15,
        },
    }

    try:
        post_data = call_gemini_api(payload, api_key, model_name=MODEL)
        is_mock = is_mock_fixture_article(article)
        return validate_post(post_data, source, url, is_mock=is_mock, article=article, source_evidence=source_summary)
    except Exception as e:
        sanitized = sanitize_gemini_error(e)
        if is_prod:
            print(f"[PRODUCTION SAFEGUARD] Gemini generation failed in production mode: {sanitized}")
            raise RuntimeError(f"Production post generation failed: {sanitized}") from e

        print(f"API calls failed ({sanitized}); falling back to verified offline generator.")
        return generate_mock_post(article)


def main():
    post_path = Path("post.json")
    if post_path.is_file():
        try:
            post_path.unlink()
        except OSError:
            pass

    article_path = Path("selected_article.json")
    if not article_path.is_file():
        print("[INFO] No selected_article.json found. Skipping post generation to preserve Gemini API quota.")
        return

    try:
        article = json.loads(article_path.read_text(encoding="utf-8"))
    except Exception:
        article = {}

    if not article or not article.get("title"):
        print("[INFO] selected_article.json is empty or invalid. Skipping post generation.")
        return

    print("Generating NEWS SNAP content...")
    try:
        post = generate_post(article)
    except Exception as e:
        if post_path.is_file():
            try:
                post_path.unlink()
            except OSError:
                pass
        print(f"[FATAL ERROR] Post generation failed: {e}", file=sys.stderr)
        sys.exit(1)

    if is_production_mode() and post.get("is_synthetic") is True:
        if post_path.is_file():
            try:
                post_path.unlink()
            except OSError:
                pass
        print("[FATAL ERROR] Production safeguard refusal: Generated post is marked synthetic.", file=sys.stderr)
        sys.exit(1)

    with open(post_path, "w", encoding="utf-8") as file:
        json.dump(post, file, ensure_ascii=False, indent=2)

    print("\nContent validation passed successfully:")
    print("Headline:", post["headline"])
    print("Curiosity:", post["curiosity_line"])
    print("Caption:", post["caption"])
    print("Hashtags:", " ".join(post["hashtags"]))


if __name__ == "__main__":
    main()

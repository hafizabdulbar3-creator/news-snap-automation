"""Prepare optional NEWS SNAP Format 04 roundup and Format 06 quote inputs.

This helper is deliberately conservative:
- Format 04 uses three distinct source articles with publisher-provided descriptions
  or extractive sentences from the source page.
- Format 06 uses a verbatim quoted span only when the source page contains the quote
  and nearby text attributes it to a named speaker. It is source-attributed, not an
  independent fact-check of the speaker's words.
- If the required evidence cannot be found, the requested mode fails closed.
"""

import html
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0
USER_AGENT = (
    "NEWS-SNAP-preview/1.0 "
    "(https://github.com/hafizabdulbar3-creator/news-snap-automation)"
)
MODE = os.environ.get("NEWS_SNAP_PREVIEW_MODE", "automatic").strip().lower()
MAX_HTML_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT = 10
MAX_ROUNDUP_CANDIDATES = 14
MAX_QUOTE_CANDIDATES = 12


def is_latin_script(text):
    if not isinstance(text, str) or not text.strip():
        return False
    for ch in text:
        if ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN "):
            return False
        if ch.isdigit() and not ch.isascii():
            return False
    return True


def is_english(text, min_confidence=0.45):
    text = re.sub(r"https?://\S+", "", str(text or "")).strip()
    if not is_latin_script(text) or sum(ch.isalpha() for ch in text) < 8:
        return False
    try:
        guesses = detect_langs(text)
        return bool(guesses and guesses[0].lang == "en" and guesses[0].prob >= min_confidence)
    except LangDetectException:
        return False


def clean_text(value):
    value = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    return re.sub(r"\s+", " ", value).strip()


class NewsPageParser(HTMLParser):
    """Small stdlib parser for Open Graph/meta tags, JSON-LD and paragraph text."""

    SKIP_TAGS = {"style", "noscript", "nav", "footer", "header", "script", "svg", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.jsonld_scripts = []
        self.paragraphs = []
        self._skip_depth = 0
        self._script_jsonld = False
        self._script_buffer = []
        self._p_depth = 0
        self._p_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): v for k, v in attrs if k}
        tag = tag.lower()
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower().strip()
            val = attrs.get("content", "")
            if key and val and key not in self.meta:
                self.meta[key] = clean_text(val)
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            if tag == "script":
                typ = (attrs.get("type") or "").lower().strip()
                self._script_jsonld = typ == "application/ld+json"
                self._script_buffer = []
        if tag == "p" and self._skip_depth == 0:
            self._p_depth += 1
            if self._p_depth == 1:
                self._p_buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "p" and self._p_depth > 0:
            self._p_depth -= 1
            if self._p_depth == 0:
                para = clean_text("".join(self._p_buffer))
                if len(para) >= 35:
                    self.paragraphs.append(para)
                self._p_buffer = []
        if tag == "script" and self._script_jsonld:
            content = "".join(self._script_buffer).strip()
            if content:
                self.jsonld_scripts.append(content)
            self._script_jsonld = False
            self._script_buffer = []
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0 and self._p_depth > 0:
            self._p_buffer.append(data)
        if self._script_jsonld:
            self._script_buffer.append(data)


def walk_jsonld(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_jsonld(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_jsonld(value)


def get_article_payload(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as response:
            raw = response.read(MAX_HTML_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
        if len(raw) > MAX_HTML_BYTES:
            print(f"Source page too large; skipping: {parsed.netloc}")
            return None
        source_html = raw.decode(charset, errors="replace")
    except Exception as exc:
        print(f"Source page unavailable ({parsed.netloc}, {type(exc).__name__}); skipping")
        return None

    parser = NewsPageParser()
    try:
        parser.feed(source_html)
    except Exception:
        pass

    article_body = ""
    jsonld_description = ""
    jsonld_headline = ""
    jsonld_author = ""
    for script in parser.jsonld_scripts:
        try:
            objects = json.loads(script)
        except Exception:
            continue
        for obj in walk_jsonld(objects):
            body = obj.get("articleBody")
            if isinstance(body, str) and len(body) > len(article_body):
                article_body = clean_text(body)
            desc = obj.get("description")
            if isinstance(desc, str) and len(desc) > len(jsonld_description):
                jsonld_description = clean_text(desc)
            head = obj.get("headline")
            if isinstance(head, str) and len(head) > len(jsonld_headline):
                jsonld_headline = clean_text(head)
            author = obj.get("author")
            if isinstance(author, dict):
                name = author.get("name")
                if isinstance(name, str):
                    jsonld_author = clean_text(name)
            elif isinstance(author, list):
                names = [clean_text(a.get("name")) for a in author if isinstance(a, dict) and a.get("name")]
                if names:
                    jsonld_author = ", ".join(names[:3])
            elif isinstance(author, str):
                jsonld_author = clean_text(author)

    paragraph_body = " ".join(parser.paragraphs)
    if len(paragraph_body) > len(article_body):
        article_body = paragraph_body

    description = (
        parser.meta.get("og:description")
        or parser.meta.get("twitter:description")
        or parser.meta.get("description")
        or parser.meta.get("article:description")
        or jsonld_description
    )
    return {
        "description": clean_text(description),
        "body": clean_text(article_body),
        "publisher_headline": jsonld_headline,
        "author": jsonld_author,
    }


def candidate_summary(payload):
    desc = payload.get("description", "")
    wc = len(desc.split())
    if 6 <= wc <= 25 and is_english(desc):
        return desc
    body = payload.get("body", "")
    # Prefer a source-extractive sentence; never invent a summary from title alone.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\u201c\"'])", body)
    for sentence in sentences[:14]:
        sentence = clean_text(sentence)
        wc = len(sentence.split())
        if 6 <= wc <= 25 and is_english(sentence) and not re.search(r"\b(read more|subscribe|sign up|click here)\b", sentence, re.I):
            return sentence
    return None


def title_key(title):
    text = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def titles_too_similar(a, b):
    aw, bw = set(title_key(a).split()), set(title_key(b).split())
    if not aw or not bw:
        return True
    intersection = len(aw & bw)
    union = len(aw | bw)
    # Use Jaccard similarity so shared common words do not discard distinct stories.
    return intersection / max(1, union) >= 0.80


def load_candidates():
    articles = json.loads(Path("discovery.json").read_text(encoding="utf-8"))
    classified = json.loads(Path("classified_sample.json").read_text(encoding="utf-8"))
    by_id = {item.get("id"): item for item in classified.get("results", []) if isinstance(item, dict)}
    result = []
    for index, article in enumerate(articles[:50], start=1):
        cls = by_id.get(index, {})
        if cls.get("importance") not in {"MAJOR", "NORMAL"}:
            continue
        title = str(article.get("title", "")).strip()
        url = str(article.get("url", "")).strip()
        domain = str(article.get("domain", "")).strip().lower()
        if not title or not url or not domain or not is_english(title):
            continue
        merged = {**article, "classification": cls}
        result.append(merged)
    return result


def name_is_plausible(name):
    name = clean_text(name).strip(" .,:;—–-")
    if not name or not is_latin_script(name):
        return False
    tokens = re.findall(r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.’\-]*", name)
    generic = {"Official", "Officials", "Spokesperson", "Spokesman", "Spokeswoman", "Authorities", "Police", "Company", "Government", "Ministry", "Agency", "Reuters", "Bloomberg", "Associated", "Press", "The", "It", "They", "He", "She", "Source", "Sources", "Analyst", "Analysts", "Witness", "Witnesses"}
    if not tokens or any(token.rstrip(".") in generic for token in tokens):
        return False
    cleaned = re.sub(r"^(?:President|Prime Minister|PM|CEO|Chancellor|Secretary|Foreign Minister|Health Minister|Minister|Senator|Governor|Dr\.?|Sir|Dame|Representative|Rep\.?|Chairman|Chairwoman|Spokesperson)\s+", "", name, flags=re.I)
    cleaned_tokens = re.findall(r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.’\-]*", cleaned)
    return len(cleaned_tokens) >= 2 or (len(cleaned_tokens) == 1 and len(cleaned_tokens[0]) >= 5)


def extract_attributed_quote(body):
    if not body:
        return None
    # Only explicit double quotation marks; do not treat apostrophes as quotes.
    quote_re = re.compile(r'[\u201c"](?P<quote>[^\u201d"\n]{25,420})[\u201d"]')
    before_patterns = [
        re.compile(r"(?P<speaker>(?:[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.’\-]*\s+){0,4}[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.’\-]*)\s+(?:said|says|told|warned|added|stated|noted|explained|argued|wrote|announced)\s*,?\s*$"),
    ]
    after_pattern = re.compile(r"^\s*(?:,|—|–|-)?\s*(?:said|says|told|warned|added|stated|noted|explained|argued|wrote|announced)\s+(?P<speaker>(?:[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.’\-]*\s+){0,4}[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.’\-]*)")
    for match in quote_re.finditer(body):
        quote = clean_text(match.group("quote")).strip(" ,;:—–-")
        wc = len(quote.split())
        if not 5 <= wc <= 45 or not is_english(quote):
            continue
        before = body[max(0, match.start() - 180):match.start()]
        after = body[match.end():match.end() + 150]
        speaker = None
        for pattern in before_patterns:
            found = pattern.search(before)
            if found:
                candidate = clean_text(found.group("speaker"))
                if name_is_plausible(candidate):
                    speaker = candidate
                    break
        if not speaker:
            found = after_pattern.search(after)
            if found:
                candidate = clean_text(found.group("speaker"))
                if name_is_plausible(candidate):
                    speaker = candidate
        if speaker:
            return {"quote_text": quote, "speaker": speaker}
    return None


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def attach_quote_to_article(article, fetch=True):
    payload = get_article_payload(article.get("url", "")) if fetch else None
    if not payload:
        return None
    found = extract_attributed_quote(payload.get("body", ""))
    if not found:
        return None
    enriched = dict(article)
    enriched.update(found)
    enriched["quote_verified"] = True
    enriched["quote_source_url"] = str(article.get("url", ""))
    enriched["quote_verification_method"] = "Exact quoted text and nearby speaker attribution found on the publisher page; not independently corroborated."
    enriched["speaker_role"] = ""
    return enriched


def prepare_roundup(candidates):
    selected = []
    seen_urls = set()
    for article in candidates[:MAX_ROUNDUP_CANDIDATES]:
        url = article["url"]
        key = title_key(article["title"])
        if url in seen_urls or any(titles_too_similar(key, s["title"]) for s in selected):
            continue
        payload = get_article_payload(url)
        if not payload:
            continue
        summary = candidate_summary(payload)
        if not summary:
            print(f"Roundup candidate skipped: no usable publisher description/body ({article['domain']})")
            continue
        if not 4 <= len(article["title"].split()) <= 14 or not is_english(article["title"]):
            continue
        selected.append({
            "title": article["title"],
            "domain": article["domain"],
            "url": url,
            "summary": summary,
            "image_search_query": article["title"],
            "classification": article.get("classification", {}),
        })
        seen_urls.add(url)
        print(f"Roundup story {len(selected)} prepared from {article['domain']}")
        if len(selected) == 3:
            break
    if len(selected) != 3:
        raise RuntimeError(
            f"Format 04 requires 3 source-backed stories; only {len(selected)} qualified. "
            "No inaccurate roundup image will be produced. Try again later."
        )

    roundup = {"stories": selected}
    roundup_post = {
        "headline": "TODAY'S TOP 3 STORIES",
        "curiosity_line": "Three important updates in one quick briefing",
        "caption": "NEWS SNAP roundup of three source-attributed headlines. Read each original report for full context.\n\n" + "\n".join(
            f"{i}. {story['title']} — {story['domain']} — {story['url']}"
            for i, story in enumerate(selected, start=1)
        ),
        "hashtags": ["#NewsSnap", "#DailyBriefing", "#GlobalNews"],
    }
    save_json("roundup.json", roundup)
    save_json("roundup_post.json", roundup_post)
    # Keep the common artifact manifest populated without another Gemini request.
    save_json("post.json", roundup_post)
    print("Format 04 inputs created: exactly 3 stories with source-backed summaries.")


def main():
    if MODE not in {"automatic", "daily_roundup", "verified_quote"}:
        raise ValueError("NEWS_SNAP_PREVIEW_MODE must be automatic, daily_roundup, or verified_quote")

    if not Path("selected_article.json").is_file():
        raise FileNotFoundError("selected_article.json is missing")

    selected_article = json.loads(Path("selected_article.json").read_text(encoding="utf-8"))
    candidates = load_candidates()

    if MODE == "daily_roundup":
        prepare_roundup(candidates)
        return

    if MODE == "automatic":
        enriched = attach_quote_to_article(selected_article)
        if enriched:
            save_json("selected_article.json", enriched)
            print("Format 06 eligible: exact quote and named attribution found on source page.")
        else:
            selected_article.pop("quote_text", None)
            selected_article.pop("speaker", None)
            selected_article.pop("quote_verified", None)
            save_json("selected_article.json", selected_article)
            print("No source-attributed quote found for selected story; topic-based single-story layout will be used.")
        return

    # verified_quote mode: search a small batch; fail closed if no suitable source quote.
    quote_candidates = []
    if selected_article.get("url"):
        quote_candidates.append(selected_article)
    quote_candidates.extend(
        a for a in candidates
        if a.get("url") != selected_article.get("url")
    )

    for article in quote_candidates[:MAX_QUOTE_CANDIDATES]:
        enriched = attach_quote_to_article(article)
        if enriched:
            save_json("selected_article.json", enriched)
            print("Format 06 source-attributed quote found.")
            print("Speaker:", enriched["speaker"])
            print("Quote:", enriched["quote_text"])
            return
    raise RuntimeError(
        "Format 06 requires an exact, source-attributed quote. None was found "
        f"in the first {MAX_QUOTE_CANDIDATES} eligible source pages. No quote card was created."
    )


if __name__ == "__main__":
    main()

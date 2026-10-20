import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException
    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

RSS_URL = "https://data.gdeltproject.org/gdeltv3/gal/feed.rss"
USER_AGENT = "NEWS-SNAP-Discovery/1.0 (https://github.com/hafizabdulbar3-creator/news-snap-automation)"
SOURCES_FILE = Path("sources.json")
HISTORY_FILE = Path("history.json")

# Standard tracking parameters stripped during URL normalization
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "at_medium", "at_campaign", "at_custom1", "at_custom2", "at_custom3", "at_custom4",
    "oc", "ref", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid"
}

# Default fallbacks if sources.json was empty or missing
DEFAULT_HIGH_TRUST = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "cnn.com",
    "aljazeera.com", "theguardian.com", "dw.com", "france24.com",
    "npr.org", "bloomberg.com", "cnbc.com", "ft.com", "wsj.com",
    "economist.com", "nytimes.com", "washingtonpost.com", "foxnews.com",
    "nbcnews.com", "cbsnews.com", "abcnews.go.com", "hindustantimes.com",
    "indianexpress.com", "thehindu.com", "ndtv.com", "indiatoday.in", "livemint.com"
}

DEFAULT_EXCLUDED_KEYWORDS = {
    "horoscope", "astrology", "rashi", "tarot", "zodiac", "box office",
    "box-office", "movie review", "film review", "trailer launch", "ott release",
    "lottery", "crossword", "daily puzzle", "dating advice", "beauty tips", "celebrity spotted"
}

DEFAULT_PRIORITY_TOPICS = {
    "president", "prime minister", "government", "parliament", "congress", "senate",
    "election", "summit", "economy", "inflation", "central bank", "trade", "war",
    "treaty", "accord", "military", "sanctions", "diplomacy", "united nations",
    "nato", "space", "artificial intelligence", "climate", "disaster"
}


def load_sources_config(config_path: Path = SOURCES_FILE) -> tuple[list[dict], set, set, set]:
    """Load configurable RSS feeds and scoring sets from sources.json with safe fallbacks."""
    sources = []
    high_trust = set(DEFAULT_HIGH_TRUST)
    excluded = set(DEFAULT_EXCLUDED_KEYWORDS)
    priority = set(DEFAULT_PRIORITY_TOPICS)

    if config_path and Path(config_path).is_file():
        try:
            cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                sources = cfg.get("rss_sources", [])
                if cfg.get("high_trust_domains"):
                    high_trust = set(cfg["high_trust_domains"])
                if cfg.get("excluded_keywords"):
                    excluded = set(cfg["excluded_keywords"])
                if cfg.get("priority_topics"):
                    priority = set(cfg["priority_topics"])
        except Exception as err:
            print(f"[WARN] Failed loading sources.json ({err}); using standard defaults.")

    if not sources:
        sources = [{
            "name": "GDELT Global News",
            "url": RSS_URL,
            "type": "gdelt",
            "enabled": True,
            "disabled": False,
            "primary": True
        }]

    return sources, high_trust, excluded, priority


# Initialize global configuration for module-level compatibility
CONFIG_SOURCES, HIGH_TRUST, EXCLUDED_KEYWORDS, PRIORITY_TOPICS = load_sources_config(SOURCES_FILE)


def load_history_duplicates(history_path: Path = HISTORY_FILE) -> tuple[set, set]:
    """Load previously posted and processed history sets to prevent story duplicates."""
    posted_urls = set()
    posted_titles = set()
    hpath = Path(history_path) if history_path else HISTORY_FILE
    if hpath.is_file():
        try:
            hist_data = json.loads(hpath.read_text(encoding="utf-8"))
            for entry in hist_data.get("posted", []):
                if entry.get("published") is True:
                    if entry.get("url"):
                        posted_urls.add(normalize_url(entry["url"]))
                    if entry.get("title"):
                        posted_titles.add(entry["title"].strip().lower())
            for entry in hist_data.get("processed", []):
                if entry.get("url"):
                    posted_urls.add(normalize_url(entry["url"]))
                if entry.get("title"):
                    posted_titles.add(entry["title"].strip().lower())
        except Exception:
            pass
    return posted_urls, posted_titles


RECENTLY_POSTED_URLS, RECENTLY_POSTED_TITLES = load_history_duplicates(HISTORY_FILE)


def normalize_url(url: str) -> str:
    """Normalize URL by lowercasing scheme/netloc, removing tracking parameters, and stripping fragments."""
    if not url or not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        path = parsed.path
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")

        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        cleaned_pairs = [(k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS]
        query = urlencode(cleaned_pairs)

        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url.strip()


def clean_title(raw_title: str) -> str:
    """Unescape HTML entities, clean replacement chars, strip prefixes/suffixes, and normalize."""
    text = html.unescape(raw_title or "").strip()
    text = text.replace("\ufffd", "'").replace("â€™", "'").replace("â€œ", '"').replace("â€\x9d", '"')
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')

    # Remove live blog/broadcast prefixes
    text = re.sub(
        r"^(?:(?:BREAKING|LIVE(?:\s+UPDATES)?|WATCH|UPDATE|EXCLUSIVE)\s*[:|–—\-]\s*)+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # If title has a pipe separating a live label, e.g. 'Event LIVE | Main Headline', keep the main headline
    if "|" in text:
        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) == 2 and any(m in parts[0].lower() for m in ("live", "breaking", "updates", "march live")):
            text = parts[1]
        elif len(parts) == 2 and any(m in parts[1].lower() for m in ("live", "breaking", "updates")):
            text = parts[0]

    # Strip common publisher suffixes
    text = re.sub(
        r"\s*[-–—|]\s*(?:BBC(?: News.*)?|The Times of India|Reuters|Al Jazeera|The Guardian|CNN|NPR|DW|France 24|Fox News|NBC News|CBS News|AP News|Bloomberg|CNBC|The Hindu|NDTV|Hindustan Times|Indian Express|India Today|LiveMint|Mint).*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # Strip trailing punctuation
    text = re.sub(r"[;:,|–—\-]+$", "", text).strip()
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    return text


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


def is_english_headline(text: str) -> bool:
    """Strictly verify that the headline is natural English and not a foreign language."""
    if not is_latin_script(text):
        return False

    tokens = [w.lower() for w in re.findall(r"[a-z]+", text)]
    if len(tokens) < 3:
        return False

    english_function_words = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
        "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
        "this", "but", "his", "by", "from", "they", "we", "say", "her",
        "she", "or", "an", "will", "my", "one", "all", "would", "there",
        "their", "what", "so", "up", "out", "if", "about", "who", "get",
        "which", "go", "me", "when", "make", "can", "like", "time", "no",
        "just", "him", "know", "take", "people", "into", "year", "your",
        "good", "some", "could", "them", "see", "other", "than", "then",
        "now", "look", "only", "come", "its", "over", "think", "also",
        "back", "after", "use", "two", "how", "our", "work", "first",
        "well", "way", "even", "new", "want", "because", "any", "these",
        "give", "day", "most", "us", "says", "said", "amid", "chief",
        "plan", "plans", "war", "court", "kills", "killed", "police"
    }

    matches = sum(1 for t in tokens if t in english_function_words)

    if LANGDETECT_AVAILABLE and len(text) >= 15:
        try:
            langs = detect_langs(text)
            if langs:
                top = langs[0]
                if top.lang != "en" and top.prob > 0.85:
                    return False
                if top.lang == "en" and top.prob >= 0.50:
                    return True
        except LangDetectException:
            pass

    return matches >= 1


def is_trivial_or_gossip(title: str, url: str) -> bool:
    """Check if story is astrology, horoscope, entertainment gossip, section landing page, or trivial filler."""
    lower_title = title.lower()
    lower_url = url.lower()
    for kw in EXCLUDED_KEYWORDS:
        if kw in lower_title or kw in lower_url:
            return True

    index_patterns = (
        "latest news & updates", "latest news and updates", "news archives",
        "category archives", "breaking news updates", "live updates & news",
        "all news headlines"
    )
    if any(pat in lower_title for pat in index_patterns):
        return True

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith(("/technology", "/world", "/business", "/politics", "/opinion", "/entertainment", "/energy-and-climate")):
        return True

    return False


def is_feed_enabled(source: dict) -> bool:
    """Check if a configured feed is enabled based on sources.json configuration.

    Safety Guard:
    A feed configured with enabled=False or disabled=True can NEVER be enabled
    by environment variables (e.g. ENABLE_FEED_BBC_NEWS=1). Disabled feeds
    strictly require explicit configuration change in sources.json after
    publisher permission is verified.
    """
    # 1. Configured disabled status is final and takes strict precedence
    if source.get("disabled") is True or source.get("enabled") is False:
        return False

    # 2. Check if an enabled feed is explicitly disabled via env var (e.g. ENABLE_FEED_NAME=0)
    name_slug = re.sub(r"[^A-Z0-9]+", "_", source.get("name", "").upper()).strip("_")
    env_override = os.environ.get(f"ENABLE_FEED_{name_slug}")
    if env_override is not None and env_override.strip().lower() in ("0", "false", "no"):
        return False

    # 3. Default to config setting
    if "enabled" in source:
        return bool(source["enabled"])
    if "disabled" in source:
        return not bool(source["disabled"])
    return True



def fetch_feed(url: str, timeout: int = 10, max_retries: int = 1) -> bytes | None:
    """Fetch raw XML content with bounded timeout and minimal retry policy."""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read()
                print(f"[FEED HTTP {resp.status}] Failed fetching {url}")
                return None
        except urllib.error.HTTPError as he:
            # 5xx errors may be transient, 4xx are permanent
            if he.code >= 500 and attempt < max_retries:
                time.sleep(1.0)
                continue
            print(f"[FEED HTTP ERROR] {url}: HTTP {he.code} - {he.reason}")
            return None
        except (urllib.error.URLError, TimeoutError) as te:
            if attempt < max_retries:
                time.sleep(1.0)
                continue
            print(f"[FEED NETWORK ERROR] {url}: {te}")
            return None
        except Exception as exc:
            print(f"[FEED UNEXPECTED ERROR] {url}: {exc}")
            return None
    return None


def parse_feed_xml(xml_bytes: bytes) -> list[dict]:
    """Parse RSS 2.0 and Atom feeds safely into a standardized list of item dictionaries."""
    if not xml_bytes or not isinstance(xml_bytes, (bytes, str)):
        return []

    try:
        if isinstance(xml_bytes, str):
            xml_bytes = xml_bytes.encode("utf-8")
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []

    entries = []

    # 1. RSS 2.0 (<item> elements)
    items = root.findall(".//item")
    if items:
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not link:
                for child in item:
                    tag_lower = child.tag.lower()
                    if tag_lower.endswith("link"):
                        link = child.attrib.get("href") or child.text or ""
                        if link:
                            break
                    elif tag_lower.endswith("guid") and (child.text or "").startswith(("http://", "https://")):
                        link = child.text.strip()
                        break

            source_elem = item.find("source")
            source_url = source_elem.attrib.get("url", "") if source_elem is not None else ""

            if title and link:
                entries.append({
                    "raw_title": title,
                    "url": link,
                    "source_url": source_url
                })
        return entries

    # 2. Atom 1.0 (<entry> elements)
    entries_elem = [e for e in root.iter() if e.tag.endswith("entry")]
    for entry in entries_elem:
        title = ""
        link = ""
        for child in entry:
            tag_lower = child.tag.lower()
            if tag_lower.endswith("title"):
                title = (child.text or "").strip()
            elif tag_lower.endswith("link"):
                href = child.attrib.get("href", "")
                rel = child.attrib.get("rel", "alternate")
                if rel in ("alternate", "") and href:
                    link = href.strip()
                elif not link and href:
                    link = href.strip()
                elif not link and (child.text or "").startswith(("http://", "https://")):
                    link = child.text.strip()
            elif tag_lower.endswith("id") and not link and (child.text or "").startswith(("http://", "https://")):
                link = child.text.strip()

        if title and link:
            entries.append({
                "raw_title": title,
                "url": link,
                "source_url": ""
            })

    return entries


def discover_articles(
    sources: list[dict] | None = None,
    history_path: Path = HISTORY_FILE,
    sources_path: Path = SOURCES_FILE
) -> list[dict]:
    """Aggregate, filter, and score candidate news stories across all enabled RSS sources."""
    cfg_sources, high_trust, excluded_keywords, priority_topics = load_sources_config(sources_path)
    if sources is None:
        sources = cfg_sources

    recently_posted_urls, recently_posted_titles = load_history_duplicates(history_path)

    articles = []
    seen_urls = set()
    seen_titles = set()

    for source in sources:
        source_name = source.get("name", "Unknown Feed")
        source_url = source.get("url", "")
        if not source_url:
            continue

        if not is_feed_enabled(source):
            reason = source.get("reason", "Disabled by configuration")
            print(f"[FEED DISABLED] {source_name}: {reason}")
            continue

        print(f"Fetching {source_name} ({source_url})...")
        timeout = int(source.get("timeout", 10))
        xml_data = fetch_feed(source_url, timeout=timeout)
        if not xml_data:
            print(f"[FEED EMPTY/FAILED] {source_name}: No response received.")
            continue

        entries = parse_feed_xml(xml_data)
        if not entries:
            print(f"[FEED PARSE] {source_name}: Parsed 0 items.")
            continue

        feed_added = 0
        for entry in entries:
            raw_title = entry["raw_title"]
            url = entry["url"]
            source_url_meta = entry.get("source_url", "")

            if not raw_title or not url:
                continue

            clean = clean_title(raw_title)
            if not clean or len(clean.split()) < 4:
                continue

            norm_url = normalize_url(url)
            norm_title = clean.strip().lower()

            if norm_url in seen_urls or norm_title in seen_titles:
                continue

            # Strict language check: Must be English
            if not is_english_headline(clean):
                continue

            # Filter out horoscopes, astrology, gossip, filler
            if is_trivial_or_gossip(clean, norm_url):
                continue

            # Determine domain (for Google News fallback, extract source domain if present)
            raw_domain = urlparse(norm_url).netloc.lower().replace("www.", "")
            if raw_domain in ("news.google.com", "google.com") and source_url_meta:
                domain = urlparse(source_url_meta).netloc.lower().replace("www.", "")
            else:
                domain = raw_domain

            seen_urls.add(norm_url)
            seen_titles.add(norm_title)

            # Check duplicate history
            is_duplicate = (
                norm_url in recently_posted_urls
                or norm_title in recently_posted_titles
            )

            score = 0
            if is_duplicate:
                score -= 1000

            if domain in high_trust:
                score += 100

            lower_clean = clean.lower()
            for topic in priority_topics:
                if topic in lower_clean:
                    score += 15

            articles.append({
                "title": clean,
                "raw_title": raw_title,
                "url": norm_url,
                "domain": domain,
                "score": score,
                "is_duplicate": is_duplicate,
                "source": source_name,
            })
            feed_added += 1

        print(f"[FEED OK] {source_name}: {feed_added} candidates accepted from {len(entries)} items.")

    # Sort candidates by score descending
    articles.sort(key=lambda x: x["score"], reverse=True)
    return articles


def main():
    print("===== NEWS SNAP DISCOVERY AGGREGATOR =====")
    articles = discover_articles()

    with open("discovery.json", "w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    print(f"\nDiscovered {len(articles)} English, high-quality candidate articles across active feeds.")
    print("\nTOP DISCOVERY CANDIDATES:\n")

    top_display = [a for a in articles if not a["is_duplicate"]][:20]
    for i, article in enumerate(top_display, start=1):
        src_info = f" [{article.get('source', 'GDELT')}]" if article.get("source") else ""
        print(f"{i}. [{article['score']} pts]{src_info} {article['title']}")
        print(f"   Domain: {article['domain']}")
        print(f"   URL: {article['url']}")
        print()


if __name__ == "__main__":
    main()

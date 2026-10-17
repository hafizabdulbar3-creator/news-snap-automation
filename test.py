import html
import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException
    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

RSS_URL = "https://data.gdeltproject.org/gdeltv3/gal/feed.rss"
USER_AGENT = "NEWS-SNAP-Discovery/1.0 (https://github.com/hafizabdulbar3-creator/news-snap-automation)"

# Load configuration from sources.json
SOURCES_FILE = Path("sources.json")
if SOURCES_FILE.is_file():
    try:
        config = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        HIGH_TRUST = set(config.get("high_trust_domains", []))
        EXCLUDED_KEYWORDS = set(config.get("excluded_keywords", []))
        PRIORITY_TOPICS = set(config.get("priority_topics", []))
    except Exception:
        HIGH_TRUST = set()
        EXCLUDED_KEYWORDS = set()
        PRIORITY_TOPICS = set()
else:
    HIGH_TRUST = set()
    EXCLUDED_KEYWORDS = set()
    PRIORITY_TOPICS = set()

# Default fallbacks if sources.json was empty or missing
if not HIGH_TRUST:
    HIGH_TRUST = {
        "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "cnn.com",
        "aljazeera.com", "theguardian.com", "dw.com", "france24.com",
        "npr.org", "bloomberg.com", "cnbc.com", "ft.com", "wsj.com",
        "economist.com", "nytimes.com", "washingtonpost.com", "foxnews.com",
        "nbcnews.com", "cbsnews.com", "abcnews.go.com", "hindustantimes.com",
        "indianexpress.com", "thehindu.com", "ndtv.com", "indiatoday.in"
    }

if not EXCLUDED_KEYWORDS:
    EXCLUDED_KEYWORDS = {
        "horoscope", "astrology", "rashi", "tarot", "zodiac", "box office",
        "box-office", "movie review", "film review", "lottery", "crossword",
        "puzzle", "dating", "beauty tips", "celebrity spotted"
    }

if not PRIORITY_TOPICS:
    PRIORITY_TOPICS = {
        "president", "prime minister", "government", "parliament", "election",
        "economy", "inflation", "market", "trade", "war", "treaty", "sanctions",
        "diplomacy", "united nations", "nato", "ukraine", "russia", "china",
        "israel", "gaza", "iran", "space", "artificial intelligence", "climate"
    }

# Load previously posted and processed history to avoid duplicates
HISTORY_FILE = Path("history.json")
RECENTLY_POSTED_URLS = set()
RECENTLY_POSTED_TITLES = set()
if HISTORY_FILE.is_file():
    try:
        hist_data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        for entry in hist_data.get("posted", []):
            if entry.get("published") is True:
                if entry.get("url"):
                    RECENTLY_POSTED_URLS.add(entry["url"].strip().lower())
                if entry.get("title"):
                    RECENTLY_POSTED_TITLES.add(entry["title"].strip().lower())
        for entry in hist_data.get("processed", []):
            if entry.get("url"):
                RECENTLY_POSTED_URLS.add(entry["url"].strip().lower())
            if entry.get("title"):
                RECENTLY_POSTED_TITLES.add(entry["title"].strip().lower())
    except Exception:
        pass


def clean_title(raw_title: str) -> str:
    """Unescape HTML entities, clean replacement chars, strip prefixes/suffixes, and normalize."""
    text = html.unescape(raw_title or "").strip()
    text = text.replace("\ufffd", "'").replace("â€™", "'").replace("â€œ", '"').replace("â€\x9d", '"')
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')

    # Remove live blog/broadcast prefixes
    text = re.sub(r"^(?:(?:BREAKING|LIVE(?:\s+UPDATES)?|WATCH|UPDATE|EXCLUSIVE)\s*[:|–—\-]\s*)+", "", text, flags=re.IGNORECASE).strip()

    # If title has a pipe separating a live label, e.g. 'Event LIVE | Main Headline', keep the main headline
    if "|" in text:
        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) == 2 and any(m in parts[0].lower() for m in ("live", "breaking", "updates", "march live")):
            text = parts[1]
        elif len(parts) == 2 and any(m in parts[1].lower() for m in ("live", "breaking", "updates")):
            text = parts[0]

    # Strip common publisher suffixes like ' - BBC News', ' | Reuters', ' - The Times of India'
    text = re.sub(
        r"\s*[-–—|]\s*(?:BBC(?: News.*)?|The Times of India|Reuters|Al Jazeera|The Guardian|CNN|NPR|DW|France 24|Fox News|NBC News|CBS News|AP News|Bloomberg|CNBC|The Hindu|NDTV|Hindustan Times|Indian Express|India Today).*$",
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

    # English common grammatical function words
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

    # If langdetect is available, use it as an additional check
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

    # Heuristic fallback: require at least one or two standard English function words
    return matches >= 1


def is_trivial_or_gossip(title: str, url: str) -> bool:
    """Check if story is astrology, horoscope, entertainment gossip, section landing page, or trivial filler."""
    lower_title = title.lower()
    lower_url = url.lower()
    for kw in EXCLUDED_KEYWORDS:
        if kw in lower_title or kw in lower_url:
            return True

    # Reject section front pages, index feeds, archives
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


def main():
    request = urllib.request.Request(
        RSS_URL,
        headers={"User-Agent": USER_AGENT}
    )

    print("Fetching GDELT discovery feed...")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            xml_data = response.read()
    except Exception as e:
        print(f"Error fetching GDELT feed: {e}")
        return

    try:
        root = ET.fromstring(xml_data)
    except Exception as e:
        print(f"Error parsing GDELT XML: {e}")
        return

    items = root.findall(".//item")
    articles = []
    seen_urls = set()

    for item in items:
        raw_title = item.findtext("title", "").strip()
        url = item.findtext("link", "").strip()

        if not raw_title or not url or url in seen_urls:
            continue

        clean = clean_title(raw_title)
        if not clean or len(clean.split()) < 4:
            continue

        seen_urls.add(url)
        norm_url = url.strip().lower()
        norm_title = clean.strip().lower()

        # Check duplicate history
        is_duplicate = (
            norm_url in RECENTLY_POSTED_URLS
            or norm_title in RECENTLY_POSTED_TITLES
        )

        domain = urlparse(url).netloc.lower().replace("www.", "")

        # Strict language check: Must be English
        if not is_english_headline(clean):
            continue

        # Filter out horoscopes, astrology, box office collections, trivia
        if is_trivial_or_gossip(clean, url):
            continue

        score = 0
        if is_duplicate:
            score -= 1000  # Penalize duplicates so fresh news comes first

        if domain in HIGH_TRUST:
            score += 100

        lower_clean = clean.lower()
        for topic in PRIORITY_TOPICS:
            if topic in lower_clean:
                score += 15

        articles.append({
            "title": clean,
            "raw_title": raw_title,
            "url": url,
            "domain": domain,
            "score": score,
            "is_duplicate": is_duplicate,
        })

    # Sort candidates by score descending
    articles.sort(key=lambda x: x["score"], reverse=True)

    with open("discovery.json", "w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    print(f"Discovered {len(articles)} English, high-quality candidate articles.")
    print("\nTOP DISCOVERY CANDIDATES:\n")

    top_display = [a for a in articles if not a["is_duplicate"]][:20]
    for i, article in enumerate(top_display, start=1):
        print(f"{i}. [{article['score']}] {article['title']}")
        print(f"   {article['domain']}")
        print(f"   {article['url']}")
        print()


if __name__ == "__main__":
    main()

"""NEWS SNAP Multi-Format Generator.

Strictly reproduces the six approved NEWS SNAP visual formats:
- Format 01: Emergency & Developing Story
- Format 02: Business & Economy
- Format 03: People & Corporate Leadership
- Format 04: Daily Headlines Roundup (Top 3 Stories)
- Format 05: Single Story News Report
- Format 06: Verified Statement / Quote

Uses Pillow layouts and, when a suitable freely reusable image is found,
a Wikimedia Commons thumbnail with a compatible licence and caption attribution.
If no suitable image can be found, the card uses clearly-labelled original vector art.
"""

import html
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

from format_registry import FORMAT_REGISTRY, classify_format_for_article

try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException
    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

WIDTH, HEIGHT = 1080, 1350
WHITE = (249, 250, 253)
INK = (9, 19, 34)
NAVY = (10, 24, 45)
NAVY2 = (17, 37, 65)
RED = (230, 31, 45)
YELLOW = (255, 207, 45)
BLUE = (73, 160, 241)
GREEN = (27, 87, 63)
MUTED = (171, 188, 208)
PALE = (241, 244, 248)

USER_AGENT = (
    "NEWS-SNAP-automation/1.0 "
    "(https://github.com/hafizabdulbar3-creator/news-snap-automation)"
)
OUTPUT = Path("news_snap_post.jpg")

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "after", "amid",
    "into", "over", "under", "about", "will", "could", "would", "should",
    "says", "said", "say", "has", "have", "had", "its", "their", "they",
    "them", "his", "her", "our", "you", "your", "are", "was", "were",
    "been", "being", "new", "latest", "today", "report", "reports", "news",
    "update", "updates", "what", "when", "where", "why", "how", "who",
}


def font(size, bold=False):
    """Load robust, high-quality system font across Ubuntu, Windows, and macOS."""
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            "DejaVuSans-Bold.ttf",
            "Arial-Bold.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "DejaVuSans.ttf",
            "Arial.ttf",
        ]
    )
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def get_current_date_str(fmt="%d %b %Y"):
    """Safe date string formatting with timezone fallback."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return now.strftime(fmt)


def is_latin_script(text):
    if not isinstance(text, str) or not text.strip():
        return False
    for ch in text:
        if ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN "):
            return False
        if ch.isdigit() and not ch.isascii():
            return False
    return True


def is_likely_english(text, minimum_confidence=0.40):
    if not is_latin_script(text):
        return False
    letters = sum(ch.isalpha() for ch in text)
    if letters < 6:
        return False
    if not LANGDETECT_AVAILABLE:
        return True
    try:
        predictions = detect_langs(text)
        return bool(
            predictions
            and predictions[0].lang == "en"
            and predictions[0].prob >= minimum_confidence
        )
    except Exception:
        return True


def validate_english_text(text, label, min_words=None, max_words=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Missing required text: {label}")
    text = text.strip()
    if not is_latin_script(text):
        raise ValueError(f"Rejected {label}: non-Latin script detected")
    # Proper names for speakers use Latin script validation rather than language classification
    if "speaker" not in label and not is_likely_english(text):
        raise ValueError(f"Rejected {label}: not confidently English")
    wc = len(text.split())
    if min_words is not None and wc < min_words:
        raise ValueError(f"Rejected {label}: too few words ({wc} < {min_words})")
    if max_words is not None and wc > max_words:
        if "quotation" in label or "quote" in label:
            raise ValueError(f"Rejected {label}: quotation exceeds {max_words} words ({wc} words). Never shorten or truncate a quotation.")
        words = text.split()[:max_words]
        text = " ".join(words)
    return text


def wrap(draw, text, ft, max_width):
    lines, current = [], ""
    for word in text.split():
        candidate = word if not current else f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=ft)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped(draw, text, box, max_size=70, min_size=24, bold=True,
                 fill=WHITE, max_lines=5, line_multiplier=1.16, align="left"):
    x1, y1, x2, y2 = box
    max_width, max_height = x2 - x1, y2 - y1
    for size in range(max_size, min_size - 1, -2):
        ft = font(size, bold)
        lines = wrap(draw, text, ft, max_width)
        line_h = int(size * line_multiplier)
        if len(lines) <= max_lines and line_h * len(lines) <= max_height:
            y = y1 + max(0, (max_height - line_h * len(lines)) // 2)
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=ft)
                text_w = bbox[2] - bbox[0]
                if align == "center":
                    x = x1 + (max_width - text_w) // 2
                else:
                    x = x1
                draw.text((x, y), line, font=ft, fill=fill)
                y += line_h
            return ft, lines

    # Fallback to min_size cleanly
    ft = font(min_size, bold)
    lines = wrap(draw, text, ft, max_width)[:max_lines]
    line_h = int(min_size * line_multiplier)
    y = y1
    for line in lines:
        draw.text((x1, y), line, font=ft, fill=fill)
        y += line_h
    return ft, lines


def draw_centered(draw, box, text, ft, fill):
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=ft)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = x1 + ((x2 - x1) - text_w) // 2
    y = y1 + ((y2 - y1) - text_h) // 2 - bbox[1]
    draw.text((x, y), text, font=ft, fill=fill)


def draw_brand_slash(draw, x=60, y=50, scale=1.0):
    w = int(22 * scale)
    h = int(44 * scale)
    slant = int(18 * scale)
    draw.polygon([
        (x, y + h),
        (x + slant, y),
        (x + slant + w, y),
        (x + w, y + h)
    ], fill=RED)
    ft = font(int(22 * scale), True)
    draw.text((x + slant + w + int(12 * scale), y - int(2 * scale)), "NEWS", font=ft, fill=WHITE)
    draw.text((x + slant + w + int(12 * scale), y + int(20 * scale)), "SNAP", font=ft, fill=WHITE)


def draw_brand_compass(draw, x=75, y=55, dark=False, scale=1.0):
    r = int(18 * scale)
    cx, cy = x + r, y + r
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(WHITE if dark else INK), width=2)
    draw.line((cx, cy - r - 3, cx, cy - r + 3), fill=(WHITE if dark else INK), width=2)
    draw.line((cx, cy + r - 3, cx, cy + r + 3), fill=(WHITE if dark else INK), width=2)
    draw.line((cx - r - 3, cy, cx - r + 3, cy), fill=(WHITE if dark else INK), width=2)
    draw.line((cx + r - 3, cy, cx + r + 3, cy), fill=(WHITE if dark else INK), width=2)
    draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=RED)

    ft = font(int(26 * scale), True)
    news_color = WHITE if dark else INK
    draw.text((x + int(48 * scale), y + int(3 * scale)), "NEWS", font=ft, fill=news_color)
    bbox = draw.textbbox((0, 0), "NEWS", font=ft)
    news_w = bbox[2] - bbox[0]
    draw.text((x + int(48 * scale) + news_w + int(8 * scale), y + int(3 * scale)), "SNAP", font=ft, fill=RED)


def draw_globe_icon(draw, cx, cy, r=13, color=WHITE):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=2)
    draw.line((cx - r, cy, cx + r, cy), fill=color, width=2)
    draw.ellipse((cx - r // 2, cy - r, cx + r // 2, cy + r), outline=color, width=2)


def draw_standard_footer(draw, category="GLOBAL NEWS", cta="DETAILS IN CAPTION ->", y=1275, dark=True):
    fg = WHITE if dark else INK
    draw_globe_icon(draw, 75, y + 14, r=13, color=fg)
    draw.text((100, y + 2), f"NEWS SNAP  |  {category.upper()}", font=font(22, True), fill=fg)
    cta_clean = cta.replace("->", "→")
    bbox = draw.textbbox((0, 0), cta_clean, font=font(22, True))
    cta_w = bbox[2] - bbox[0]
    draw.text((1015 - cta_w, y + 2), cta_clean, font=font(22, True), fill=fg)


def draw_two_tone_headline(draw, text, box, accent_mode="bottom_yellow", max_size=58, min_size=34, max_lines=4, with_shadow=False):
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1

    best_size = min_size
    best_lines = [text]
    for sz in range(max_size, min_size - 1, -2):
        ft = font(sz, bold=True)
        lines = wrap(draw, text, ft, max_w)
        line_h = int(sz * 1.16)
        if len(lines) <= max_lines and len(lines) * line_h <= max_h:
            best_size = sz
            best_lines = lines
            break

    ft = font(best_size, bold=True)
    line_h = int(best_size * 1.16)
    curr_y = y1

    for idx, line in enumerate(best_lines):
        if accent_mode == "top_yellow":
            col = YELLOW if idx == 0 else WHITE
        elif accent_mode == "bottom_yellow":
            col = YELLOW if idx == len(best_lines) - 1 else WHITE
        elif accent_mode == "all_black":
            col = INK
        elif accent_mode == "all_white":
            col = WHITE
        else:
            col = WHITE
        if with_shadow and col != INK:
            draw.text((x1 + 3, curr_y + 3), line, font=ft, fill=(0, 0, 0, 220))
        draw.text((x1, curr_y), line, font=ft, fill=col)
        curr_y += line_h
    return ft, best_lines


def extract_matching_category_tags(article):
    """Derive authentic category tags matching the article."""
    topic = str(article.get("classification", {}).get("topic", "")).strip()
    title = str(article.get("title", "")).lower()

    tags = []
    if any(k in title or k in topic.lower() for k in ("energy", "clean power", "climate", "solar", "wind", "transition")):
        tags = ["Clean Energy", "Policy", "Global"]
    elif any(k in title or k in topic.lower() for k in ("tech", "software", "ai", "electric", "automotive", "tesla")):
        tags = ["Technology", "Automotive", "Business"]
    elif any(k in title or k in topic.lower() for k in ("economy", "market", "trade", "finance", "inflation")):
        tags = ["Economy", "Markets", "Finance"]
    elif any(k in title or k in topic.lower() for k in ("diplomacy", "summit", "nations", "un")):
        tags = ["Diplomacy", "World News", "Leadership"]
    elif topic:
        tags = [topic[:16], "Leadership", "News"]
    else:
        tags = ["Leadership", "Corporate", "Global"]

    colors = [(11, 99, 206), (94, 43, 151), (22, 128, 57)]
    return list(zip(tags[:3], colors[:len(tags[:3])]))


def brand(draw, x=42, y=32, compact=False):
    draw_brand_slash(draw, x, y, scale=0.9 if compact else 1.2)


def gradient(height=HEIGHT, top=(5, 12, 25), bottom=(12, 29, 51)):
    image = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 255))
    d = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        colour = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,)
        d.line((0, y, WIDTH, y), fill=colour)
    return image


def clean_html(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


GENERIC_HEADLINE_VERBS = {
    "increases", "decreases", "raises", "lowers", "signals", "warns",
    "approves", "unveils", "announces", "launches", "surges", "drops",
    "falls", "rises", "climbs", "slumps", "urges", "targets", "faces",
    "reveals", "confirms", "denies", "declares", "orders", "halts",
    "suspends", "expands", "cuts", "adjusts", "adopts", "urged", "warned",
    "approved", "announced", "launched", "unveiled", "extended", "extends",
    "completes", "complete", "outlines", "outline", "sweeps", "sweep",
    "gather", "gathers", "reaches", "prompts", "sets", "takes", "makes",
}

KNOWN_ENTITIES = [
    "International Criminal Court", "International Court of Justice",
    "International Space Station", "United Nations", "Federal Reserve",
    "European Union", "White House", "Supreme Court", "Wall Street",
    "World Bank", "Bank of England", "European Central Bank",
    "Silicon Valley", "Red Cross", "Downing Street", "Jasper National Park",
    "National Park", "World Health Organization", "International Monetary Fund",
    "European Commission", "Security Council", "Department of Homeland Security",
]

ACRONYM_DISAMBIGUATIONS = {
    "ICC": {
        "court": {
            "keywords": {"court", "sanction", "sanctions", "prosecutor", "hague", "investigation", "warrant", "judge", "justice", "war crimes", "tribunal", "legal", "official", "officials"},
            "expanded": "International Criminal Court",
            "conflicts": {"commerce centre", "hong kong", "kowloon", "skyscraper", "tallest building", "cricket", "stadium", "champions trophy", "world cup"},
        },
        "cricket": {
            "keywords": {"cricket", "match", "tournament", "trophy", "batsman", "bowler", "wicket", "innings", "t20", "odi", "bcci", "world cup"},
            "expanded": "International Cricket Council",
            "conflicts": {"court", "hague", "sanction", "prosecutor", "war crimes", "commerce centre", "skyscraper"},
        },
    },
    "ICJ": {
        "court": {
            "keywords": {"court", "justice", "hague", "ruling", "dispute", "genocide", "un", "tribunal", "legal"},
            "expanded": "International Court of Justice",
            "conflicts": {"institute", "cricket", "commerce"},
        },
    },
    "SEC": {
        "finance": {
            "keywords": {"securities", "exchange", "commission", "fraud", "stocks", "wall street", "crypto", "investor", "fund", "gensler", "market", "trading"},
            "expanded": "Securities and Exchange Commission",
            "conflicts": {"southeastern conference", "football", "alabama", "georgia", "ncaa", "touchdown"},
        },
        "sports": {
            "keywords": {"football", "college", "conference", "touchdown", "ncaa", "quarterback"},
            "expanded": "Southeastern Conference",
            "conflicts": {"securities", "exchange commission", "fraud", "crypto"},
        },
    },
    "WHO": {
        "health": {
            "keywords": {"health", "disease", "pandemic", "virus", "vaccine", "outbreak", "medical", "hospital", "organization", "geneva"},
            "expanded": "World Health Organization",
            "conflicts": {"rock band", "pete townshend", "roger daltrey", "guitarist", "concert", "album"},
        },
    },
    "COP": {
        "climate": {
            "keywords": {"climate", "summit", "conference", "emissions", "un", "dubai", "baku", "glasgow", "paris", "environment", "warming", "fossil"},
            "expanded": "UN Climate Change Conference",
            "conflicts": {"police", "officer", "patrol", "handcuffs", "cop car", "sheriff", "arrest"},
        },
    },
    "IMF": {
        "finance": {
            "keywords": {"fund", "monetary", "loan", "economy", "bailout", "debt", "inflation", "gdp"},
            "expanded": "International Monetary Fund",
            "conflicts": {"impossible mission force", "movie", "film"},
        },
    },
    "FDA": {
        "health": {
            "keywords": {"drug", "food", "medicine", "approval", "vaccine", "treatment", "health", "pharmaceutical", "fda"},
            "expanded": "Food and Drug Administration",
            "conflicts": set(),
        },
    },
    "EPA": {
        "environment": {
            "keywords": {"environment", "pollution", "emission", "clean", "water", "air", "environmental"},
            "expanded": "Environmental Protection Agency",
            "conflicts": {"pressphoto"},
        },
    },
}


def resolve_acronym_and_conflicts(title: str, text_context: str = ""):
    """Detect acronyms in title, resolve to full entity names using context, and identify conflict keywords."""
    combined_context = f"{title} {text_context}".lower()
    context_tokens = set(re.findall(r"[a-z0-9]+", combined_context))

    resolved_queries = []
    conflict_terms = set()
    raw_acronyms = set(re.findall(r"\b[A-Z]{2,6}\b", title))

    stop_acronyms = {"NEWS", "SNAP", "LIVE", "TOP", "DAILY", "POST", "AND", "THE", "FOR", "WITH", "NEW", "ALL"}
    raw_acronyms -= stop_acronyms

    for acr in sorted(raw_acronyms):
        if acr in ACRONYM_DISAMBIGUATIONS:
            senses = ACRONYM_DISAMBIGUATIONS[acr]
            best_sense = None
            max_matches = 0
            for sense_key, sense_info in senses.items():
                kw_matches = len(context_tokens.intersection(sense_info["keywords"]))
                if kw_matches > max_matches:
                    max_matches = kw_matches
                    best_sense = sense_info

            if best_sense and max_matches >= 1:
                resolved_queries.append(best_sense["expanded"])
                conflict_terms.update(best_sense["conflicts"])
            else:
                # Ambiguous without clear context match: DO NOT search bare acronym!
                pass
        else:
            # For general unambiguous acronyms (e.g. USCIS, EAD, NATO, NASA)
            if len(acr) >= 3:
                resolved_queries.append(acr)

    return resolved_queries, conflict_terms


def name_is_plausible(name):
    name = str(name or "").strip(" .,:;—–-")
    if not name or not is_latin_script(name):
        return False
    tokens = re.findall(r"[A-Z][A-Za-z'.\-]*", name)
    generic = {
        "Official", "Officials", "Spokesperson", "Spokesman", "Spokeswoman",
        "Authorities", "Police", "Company", "Government", "Ministry", "Agency",
        "Reuters", "Bloomberg", "Associated", "Press", "The", "It", "They",
        "He", "She", "Source", "Sources", "Analyst", "Analysts", "Witness",
    }
    if not tokens or any(token.rstrip(".") in generic for token in tokens):
        return False
    cleaned = re.sub(
        r"^(?:President|Prime Minister|PM|CEO|Chancellor|Secretary|Foreign Minister|"
        r"Health Minister|Minister|Senator|Governor|Dr\.?|Sir|Dame|Representative|"
        r"Rep\.?|Chairman|Chairwoman|Spokesperson)\s+", "", name, flags=re.I
    )
    cleaned_tokens = re.findall(r"[A-Z][A-Za-z'.\-]*", cleaned)
    return len(cleaned_tokens) >= 2 or (len(cleaned_tokens) == 1 and len(cleaned_tokens[0]) >= 5)


def words_for_query(text):
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return [w for w in tokens if len(w) >= 3 and w not in STOP_WORDS and w not in GENERIC_HEADLINE_VERBS][:8]


MAP_DIAGRAM_DISQUALIFIERS = {
    "map", "maps", "mapping", "satellite", "aviris", "modis", "copernicus",
    "heat signature", "infrared", "orbit", "sensor", "diagram", "chart",
    "graph", "screenshot", "icon", "logo", "symbol", "infographic", "drawing",
    "flag", "flags", "coat of arms", "seal", "stamp", "postage", "banknote",
    "coin", "currency note", "vector", "svg", "clipart", "caricature", "meme"
}


def license_allowed(short_name):
    low = re.sub(r"\s+", " ", str(short_name or "").strip().lower())
    if not low:
        return False
    # Strictly forbid non-commercial, no-derivatives, and proprietary licences
    if any(m in low for m in (
        "noncommercial", "non-commercial", "by-nc", "-nc",
        "no derivatives", "noderivatives", "by-nd", "-nd",
        "all rights reserved", "fair use", "copyrighted"
    )):
        return False
    if "cc0" in low or "public domain" in low or "godl" in low or "attribution" in low:
        return True
    if low.startswith("pd") or " pd " in f" {low} " or "pd-" in low:
        return True
    return "cc by" in low or "cc-by" in low


def build_photo_search_queries(article, fallback_query=""):
    """Extract prioritized, high-signal entity and topic search queries for Wikimedia Commons."""
    if not isinstance(article, dict):
        q = str(article or fallback_query or "").strip()
        if not q:
            return []
        resolved, _ = resolve_acronym_and_conflicts(q, "")
        res = list(resolved)
        if q not in res and len(q.split()) >= 2:
            res.append(q)
        return res

    title = str(article.get("title") or fallback_query or "").strip()
    speaker = str(article.get("speaker") or "").strip()
    explicit_query = str(article.get("image_search_query") or "").strip()
    topic = str(article.get("classification", {}).get("topic") or "").strip()
    summary = str(article.get("summary") or article.get("description") or "").strip()

    queries = []

    # 1. Explicit search query if provided and not generic
    if explicit_query and explicit_query.lower() not in {"breaking news", "news", "update"}:
        queries.append(explicit_query)

    # 2. Speaker or person name
    if speaker and name_is_plausible(speaker):
        queries.append(speaker)

    # 3. Known multi-word organizations / entities
    for ke in KNOWN_ENTITIES:
        if re.search(r"\b" + re.escape(ke) + r"\b", title, re.IGNORECASE):
            if ke not in queries:
                queries.append(ke)

    # 4. Disambiguated acronyms using context (never search bare ambiguous acronyms like ICC)
    resolved_acrs, _ = resolve_acronym_and_conflicts(title, f"{topic} {summary}")
    for racr in resolved_acrs:
        if racr not in queries:
            queries.append(racr)

    # 5. Salient proper noun phrases (e.g. "Satya Nadella", "Jasper National Park")
    words = title.split()
    chunks = []
    curr = []
    for w in words:
        clean = re.sub(r"[^A-Za-z0-9]", "", w)
        if clean.lower() in GENERIC_HEADLINE_VERBS or clean.lower() in STOP_WORDS:
            if curr:
                chunks.append(" ".join(curr))
                curr = []
        elif clean and clean[0].isupper():
            curr.append(clean)
        else:
            if curr:
                chunks.append(" ".join(curr))
                curr = []
    if curr:
        chunks.append(" ".join(curr))

    for ch in chunks:
        ch_tokens = ch.split()
        if 2 <= len(ch_tokens) <= 4:
            if ch not in queries and ch.lower() not in {"breaking news", "live update", "daily briefing"}:
                queries.append(ch)

    # 6. Salient nouns from headline without action verbs or stop words
    tokens = [w for w in re.findall(r"[A-Za-z0-9]+", title) if len(w) >= 3]
    salient = [w for w in tokens if w.lower() not in GENERIC_HEADLINE_VERBS and w.lower() not in STOP_WORDS]
    if len(salient) >= 2:
        queries.append(" ".join(salient[:3]))

    # 7. Category / topic fallback
    if topic and topic.lower() not in {"global news", "general", "news"}:
        queries.append(topic)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for q in queries:
        clean_q = " ".join(q.split())
        q_norm = clean_q.lower()
        if q_norm and q_norm not in seen:
            seen.add(q_norm)
            deduped.append(clean_q)
    return deduped


def query_commons_image(query_or_article, require_all_terms=False):
    if os.environ.get("NEWS_SNAP_OFFLINE_PREVIEW") == "1":
        return None

    conflict_terms = set()
    if isinstance(query_or_article, dict):
        candidate_queries = build_photo_search_queries(query_or_article)
        title_context = str(query_or_article.get("title", ""))
        topic_context = str(query_or_article.get("classification", {}).get("topic", ""))
        summary_context = str(query_or_article.get("summary", "") or query_or_article.get("description", ""))
        _, conflict_terms = resolve_acronym_and_conflicts(title_context, f"{topic_context} {summary_context}")
    elif isinstance(query_or_article, str):
        candidate_queries = build_photo_search_queries({}, fallback_query=query_or_article)
        if query_or_article and query_or_article not in candidate_queries:
            candidate_queries.insert(0, query_or_article)
        _, conflict_terms = resolve_acronym_and_conflicts(query_or_article, "")
    else:
        return None

    if not candidate_queries:
        print("Photo sourcing: no useful search queries; using labelled illustration.")
        return None

    if require_all_terms:
        first_q = candidate_queries[0]
        words = words_for_query(first_q)
        if len(words) < 2:
            print("Photo sourcing: speaker name is too short to identify a portrait safely.")
            return None
        candidate_queries = [first_q]

    for query in candidate_queries[:3]:
        query_terms = words_for_query(query)[:5]
        if not query_terms:
            continue
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": "filetype:bitmap " + " ".join(query_terms),
            "gsrnamespace": 6,
            "gsrlimit": 15,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|dimensions|size",
            "iiurlwidth": 1200,
            "format": "json",
        }
        request_url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(request_url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                data = json.load(response)
        except Exception as exc:
            print(f"Photo sourcing: Commons search unavailable for '{query}' ({type(exc).__name__}).")
            continue

        pages = data.get("query", {}).get("pages", {})
        if isinstance(pages, dict):
            pages = list(pages.values())
        best = None
        best_score = 0.0
        query_set = set(query_terms)
        for page in pages:
            info_list = page.get("imageinfo", [])
            if not info_list:
                continue
            info = info_list[0]
            metadata = info.get("extmetadata", {})
            license_name = clean_html(metadata.get("LicenseShortName", {}).get("value", ""))
            if not license_allowed(license_name):
                continue

            orig_w = int(info.get("width") or 0)
            orig_h = int(info.get("height") or 0)
            if orig_w < 400 or orig_h < 400:
                continue
            ar = orig_w / max(1, orig_h)
            if ar < 0.35 or ar > 2.8:
                continue

            file_size = int(info.get("size") or 0)
            if file_size > 0 and (file_size < 20 * 1024 or file_size > 25 * 1024 * 1024):
                continue

            title = clean_html(page.get("title", "").replace("File:", ""))
            description = clean_html(metadata.get("ImageDescription", {}).get("value", ""))
            if not is_latin_script(title):
                continue
            if any(bad in title.lower() for bad in MAP_DIAGRAM_DISQUALIFIERS):
                continue
            candidate_text = (title + " " + description).lower()

            # Disqualify candidate images that represent conflicting entities
            has_conflict = False
            for conflict_phrase in conflict_terms:
                if conflict_phrase in candidate_text:
                    print(f"Photo sourcing: rejected candidate '{title}' due to entity conflict with story context ('{conflict_phrase}').")
                    has_conflict = True
                    break
            if has_conflict:
                continue

            normalized_candidate = unicodedata.normalize("NFKD", candidate_text).encode("ascii", "ignore").decode("ascii")
            candidate_tokens = set(re.findall(r"[a-z0-9]+", normalized_candidate))
            matches = query_set.intersection(candidate_tokens)
            score = len(matches) / max(1, len(query_set))
            required_matches = len(query_set) if require_all_terms else min(2, len(query_set))
            if len(matches) < required_matches or score < 0.30 or score <= best_score:
                continue

            artist = clean_html(metadata.get("Artist", {}).get("value", ""))
            if "cc by" in license_name.lower() and (not artist or not is_latin_script(artist)):
                continue
            license_url = clean_html(metadata.get("LicenseUrl", {}).get("value", ""))
            thumb = info.get("thumburl") or info.get("url")
            page_url = info.get("descriptionurl", "")
            if not thumb or not page_url or not page_url.startswith("https://commons.wikimedia.org/"):
                continue

            best_score = score
            best = {
                "title": title,
                "artist": artist or "Public-domain / CC0 work",
                "license": license_name,
                "license_url": license_url,
                "page_url": page_url,
                "thumb_url": thumb,
                "description": description,
                "score": score,
            }

        if best:
            try:
                image_req = urllib.request.Request(best["thumb_url"], headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(image_req, timeout=15) as response:
                    raw = response.read(10 * 1024 * 1024 + 1)
                if len(raw) > 10 * 1024 * 1024:
                    continue
                with Image.open(BytesIO(raw)) as im:
                    best["image"] = im.convert("RGB")
                safe_license = unicodedata.normalize("NFKD", best["license"]).encode("ascii", "ignore").decode("ascii")
                print(f"Photo sourcing: accepted Commons image for '{query}' (licence={safe_license}, match={best['score']:.2f}).")
                return best
            except Exception as exc:
                print(f"Photo sourcing: download failed ({type(exc).__name__}); trying next query.")
                continue

    print("Photo sourcing: no sufficiently relevant, approved-license result; using labelled illustration.")
    return None


def category_label(article):
    raw = str(article.get("classification", {}).get("topic", "global news")).lower()
    tokens = set(re.findall(r"[a-z]+", raw))
    rules = [
        ({"technology", "tech", "software", "artificial", "computer", "ai"}, "TECHNOLOGY"),
        ({"business", "economy", "finance", "market", "trade", "stock"}, "BUSINESS"),
        ({"health", "medical", "disease", "hospital", "medicine"}, "HEALTH"),
        ({"science", "space", "research", "physics"}, "SCIENCE"),
        ({"sports", "sport", "football", "cricket", "tennis"}, "SPORTS"),
        ({"politics", "politic", "war", "international", "relation", "world", "conflict", "diplomacy", "government"}, "WORLD NEWS"),
        ({"entertainment", "movie", "music", "celebrity", "film"}, "ENTERTAINMENT"),
    ]
    for keys, label in rules:
        if tokens.intersection(keys):
            return label
    return "GLOBAL NEWS"


def emergency_event_label(title):
    t = title.lower()
    rules = [
        (("wildfire", "wildfires", "forest fire", "forest fires"), "FOREST FIRES"),
        (("flood", "floods", "flooding"), "FLOOD EMERGENCY"),
        (("earthquake", "quake", "aftershock"), "EARTHQUAKE UPDATE"),
        (("hurricane", "cyclone", "typhoon"), "SEVERE STORM"),
        (("volcano", "volcanic eruption"), "VOLCANIC ACTIVITY"),
        (("evacuation", "evacuations"), "EVACUATION UPDATE"),
        (("explosion", "blast"), "EXPLOSION REPORT"),
        (("landslide", "mudslide"), "LANDSLIDE UPDATE"),
        (("tsunami",), "TSUNAMI UPDATE"),
    ]
    for needles, label in rules:
        if any(n in t for n in needles):
            return label
    return "DEVELOPING NEWS"


def summary_from_caption(caption, max_words=36):
    text = str(caption or "").strip()
    text = re.split(r"\n\s*(?:Source:|Original report:|(?:Illustrative )?image credit:|Image licence:|Image source:)", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"\s+", " ", text)

    sentences = re.split(r'(?<=[.!?])\s+', text)
    fitted = []
    current_count = 0
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        s_words = len(s_clean.split())
        if current_count + s_words <= max_words:
            fitted.append(s_clean)
            current_count += s_words
        else:
            break

    if fitted:
        text = " ".join(fitted).strip()
    else:
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words]).rstrip(" ,;:-")

    text = text.rstrip(".… ") + "."
    text = text or "Read the original report for full details and context."
    return validate_english_text(text, "visible summary")


def add_pill(draw, box, text, fill=RED, text_fill=WHITE, max_font=28):
    draw.rounded_rectangle(box, radius=15, fill=fill)
    draw_centered(draw, box, text, font(max_font, True), text_fill)


def crop_photo(canvas, photo_info, box, category="GLOBAL NEWS", centering=(0.5, 0.5), article=None):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if photo_info and isinstance(photo_info.get("image"), Image.Image):
        try:
            photo = ImageOps.fit(photo_info["image"], (w, h), method=Image.Resampling.LANCZOS, centering=centering)
            canvas.paste(photo.convert("RGBA"), (x1, y1))
            return True
        except Exception as exc:
            print(f"Photo cropping failed ({type(exc).__name__}); falling back to editorial illustration.")
    fallback = make_illustration(w, h, category, article=article)
    canvas.paste(fallback.convert("RGBA"), (x1, y1))
    return False


def create_vector_gradient(w, h, top_rgb, bot_rgb):
    im = Image.new("RGB", (w, h), top_rgb)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top_rgb[0] * (1 - t) + bot_rgb[0] * t)
        g = int(top_rgb[1] * (1 - t) + bot_rgb[1] * t)
        b = int(top_rgb[2] * (1 - t) + bot_rgb[2] * t)
        d.line((0, y, w, y), fill=(r, g, b))
    return im, d


def draw_editorial_pill(d, w, h, label, accent=(230, 31, 45), fill=(10, 18, 30)):
    bw = max(180, min(int(w * 0.70), 380))
    bh = max(22, min(int(h * 0.12), 34))
    bx1 = (w - bw) // 2
    by1 = max(8, int(h * 0.84))
    if by1 + bh > h - 6:
        by1 = h - bh - 6
    d.rounded_rectangle((bx1, by1, bx1 + bw, by1 + bh), radius=bh // 2, fill=fill, outline=accent, width=1)
    f_size = max(10, min(15, bh // 2 + 1))
    draw_centered(d, (bx1, by1, bx1 + bw, by1 + bh), f"NEWS SNAP • {label}", font(f_size, True), (245, 248, 255))


def render_finance_illustration(w, h):
    im, d = create_vector_gradient(w, h, (10, 24, 48), (5, 12, 24))
    ax_x1, ax_x2 = int(w * 0.10), int(w * 0.90)
    ax_y1, ax_y2 = int(h * 0.15), int(h * 0.75)
    for gy in range(ax_y1, ax_y2 + 1, max(25, (ax_y2 - ax_y1) // 3)):
        d.line((ax_x1, gy, ax_x2, gy), fill=(25, 45, 75), width=1)
    d.line((ax_x1, ax_y2, ax_x2, ax_y2), fill=(60, 95, 140), width=2)
    step = (ax_x2 - ax_x1) // 6
    candle_w = max(4, step // 3)
    c_data = [
        (0.62, 0.45, 0.70, 0.40, True),
        (0.48, 0.58, 0.62, 0.42, False),
        (0.55, 0.35, 0.60, 0.30, True),
        (0.38, 0.48, 0.52, 0.34, False),
        (0.44, 0.22, 0.50, 0.18, True)
    ]
    trend_pts = []
    for idx, (open_r, close_r, high_r, low_r, bullish) in enumerate(c_data):
        bx = ax_x1 + (idx + 1) * step
        yo, yc = int(ax_y1 + open_r * (ax_y2 - ax_y1)), int(ax_y1 + close_r * (ax_y2 - ax_y1))
        yh, yl = int(ax_y1 + high_r * (ax_y2 - ax_y1)), int(ax_y1 + low_r * (ax_y2 - ax_y1))
        fill_col = (40, 190, 110) if bullish else (235, 65, 80)
        d.line((bx, yh, bx, yl), fill=fill_col, width=max(1, candle_w // 4))
        d.rectangle((bx - candle_w // 2, min(yo, yc), bx + candle_w // 2, max(yo, yc)), fill=fill_col)
        trend_pts.append((bx, min(yo, yc)))
    if len(trend_pts) >= 2:
        d.line(trend_pts, fill=(255, 207, 45), width=max(2, w // 350))
        for pt in trend_pts:
            d.ellipse((pt[0] - 3, pt[1] - 3, pt[0] + 3, pt[1] + 3), fill=(255, 255, 255), outline=(255, 207, 45), width=2)
    draw_editorial_pill(d, w, h, "FINANCIAL GRAPHIC", accent=(255, 207, 45), fill=(10, 24, 45))
    return im


def render_crisis_illustration(w, h):
    im, d = create_vector_gradient(w, h, (32, 12, 14), (14, 16, 24))
    cx, cy = w // 2, int(h * 0.44)
    r = int(min(w, h) * 0.34)
    for fr in (0.35, 0.68, 1.0):
        cr = int(r * fr)
        d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), outline=(180, 50, 50), width=1)
    d.line((cx - r - 10, cy, cx + r + 10, cy), fill=(140, 45, 45), width=1)
    d.line((cx, cy - r - 10, cx, cy + r + 10), fill=(140, 45, 45), width=1)
    tw = max(18, int(r * 0.55))
    th = int(tw * 0.86)
    t_top = (cx, cy - th // 2)
    t_left = (cx - tw // 2, cy + th // 2)
    t_right = (cx + tw // 2, cy + th // 2)
    d.polygon([t_top, t_left, t_right], fill=(60, 18, 20), outline=(245, 60, 45))
    draw_centered(d, (cx - tw // 2, cy - th // 2, cx + tw // 2, cy + th // 2 + 4), "!", font(max(14, tw // 2), True), (255, 220, 50))
    draw_editorial_pill(d, w, h, "EMERGENCY MONITORING", accent=(230, 31, 45), fill=(28, 12, 16))
    return im


def render_diplomacy_illustration(w, h, label="GLOBAL AFFAIRS GRAPHIC"):
    import math
    im, d = create_vector_gradient(w, h, (10, 24, 48), (5, 14, 28))
    cx, cy = w // 2, int(h * 0.44)
    r = int(min(w, h) * 0.34)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(60, 130, 210), width=2)
    for py_off in (-0.5, 0.5):
        pr = int(r * math.cos(math.asin(abs(py_off))))
        py = int(cy + r * py_off)
        d.ellipse((cx - pr, py - int(r * 0.15), cx + pr, py + int(r * 0.15)), outline=(45, 90, 150), width=1)
    d.line((cx, cy - r, cx, cy + r), fill=(45, 90, 150), width=1)
    d.ellipse((cx - int(r * 0.48), cy - r, cx + int(r * 0.48), cy + r), outline=(45, 90, 150), width=1)
    nodes = [
        (cx - int(r * 0.45), cy - int(r * 0.2)),
        (cx + int(r * 0.3), cy - int(r * 0.4)),
        (cx + int(r * 0.5), cy + int(r * 0.1)),
        (cx - int(r * 0.2), cy + int(r * 0.45)),
        (cx + int(r * 0.1), cy + int(r * 0.5))
    ]
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            d.line((nodes[i], nodes[j]), fill=(80, 160, 240), width=1)
    for nx, ny in nodes:
        d.ellipse((nx - 4, ny - 4, nx + 4, ny + 4), fill=(255, 255, 255), outline=(70, 160, 240), width=2)
    draw_editorial_pill(d, w, h, label, accent=(70, 160, 240), fill=(10, 24, 45))
    return im


def render_tech_illustration(w, h):
    im, d = create_vector_gradient(w, h, (8, 20, 36), (4, 10, 20))
    cx, cy = w // 2, int(h * 0.44)
    span_x = int(w * 0.32)
    span_y = int(h * 0.28)
    l1 = [(cx - span_x, cy - int(span_y * 0.6)), (cx - span_x, cy), (cx - span_x, cy + int(span_y * 0.6))]
    l2 = [(cx, cy - span_y), (cx, cy - int(span_y * 0.33)), (cx, cy + int(span_y * 0.33)), (cx, cy + span_y)]
    l3 = [(cx + span_x, cy - int(span_y * 0.4)), (cx + span_x, cy + int(span_y * 0.4))]
    for p1 in l1:
        for p2 in l2:
            d.line((p1, p2), fill=(30, 80, 120), width=1)
    for p2 in l2:
        for p3 in l3:
            d.line((p2, p3), fill=(40, 110, 160), width=1)
    for pts, col in [(l1, (70, 170, 240)), (l2, (100, 210, 255)), (l3, (255, 207, 45))]:
        for px, py in pts:
            d.ellipse((px - 5, py - 5, px + 5, py + 5), fill=col, outline=(255, 255, 255), width=1)
    draw_editorial_pill(d, w, h, "TECHNOLOGY GRAPHIC", accent=(100, 210, 255), fill=(8, 20, 36))
    return im


def render_gov_illustration(w, h):
    im, d = create_vector_gradient(w, h, (18, 24, 38), (10, 14, 22))
    cx, cy = w // 2, int(h * 0.44)
    gw = int(min(w * 0.65, h * 0.75))
    gh = int(gw * 0.65)
    top_y = cy - gh // 2
    frieze_y = top_y + int(gh * 0.32)
    base_y = cy + gh // 2
    d.polygon([(cx, top_y), (cx - gw // 2, frieze_y), (cx + gw // 2, frieze_y)], fill=(30, 42, 62), outline=(180, 200, 225), width=2)
    d.rectangle((cx - gw // 2 - 4, frieze_y, cx + gw // 2 + 4, frieze_y + int(gh * 0.08)), fill=(40, 54, 78), outline=(180, 200, 225), width=1)
    d.rectangle((cx - gw // 2 - 10, base_y - int(gh * 0.08), cx + gw // 2 + 10, base_y), fill=(35, 48, 70), outline=(180, 200, 225), width=1)
    col_top = frieze_y + int(gh * 0.08)
    col_bot = base_y - int(gh * 0.08)
    col_step = gw // 5
    col_w = max(6, col_step // 4)
    for i in range(1, 5):
        col_x = (cx - gw // 2) + i * col_step
        d.rectangle((col_x - col_w // 2, col_top, col_x + col_w // 2, col_bot), fill=(45, 60, 85), outline=(180, 200, 225), width=1)
    draw_editorial_pill(d, w, h, "INSTITUTIONAL ILLUSTRATION", accent=(180, 200, 225), fill=(18, 24, 38))
    return im


def render_quote_illustration(w, h):
    im, d = create_vector_gradient(w, h, (8, 38, 26), (4, 20, 14))
    cx, cy = w // 2, int(h * 0.44)
    q_font = font(max(36, min(int(h * 0.38), 120)), True)
    draw_centered(d, (cx - int(w * 0.25), cy - int(h * 0.25), cx - int(w * 0.05), cy + int(h * 0.05)), "“", q_font, (35, 130, 80))
    bar_count = 11
    bar_w = max(4, min(int(w * 0.03), 12))
    gap = max(3, bar_w // 2)
    total_w = bar_count * bar_w + (bar_count - 1) * gap
    start_x = cx - total_w // 2
    height_factors = [0.2, 0.4, 0.7, 0.9, 0.6, 1.0, 0.8, 0.5, 0.85, 0.45, 0.25]
    max_bar_h = int(h * 0.28)
    for i in range(bar_count):
        bh = int(max_bar_h * height_factors[i])
        bx = start_x + i * (bar_w + gap)
        by = cy + int(h * 0.12) - bh // 2
        d.rounded_rectangle((bx, by, bx + bar_w, by + bh), radius=bar_w // 2, fill=(45, 160, 95))
    draw_editorial_pill(d, w, h, "STATEMENT ILLUSTRATION", accent=(45, 160, 95), fill=(8, 36, 24))
    return im


def render_global_illustration(w, h):
    im, d = create_vector_gradient(w, h, (14, 26, 46), (8, 14, 26))
    cx, cy = w // 2, int(h * 0.44)
    r = int(min(w, h) * 0.34)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(70, 110, 160), width=1)
    d.ellipse((cx - int(r * 0.6), cy - int(r * 0.6), cx + int(r * 0.6), cy + int(r * 0.6)), outline=(90, 140, 200), width=2)
    d.line((cx - r - 8, cy, cx + r + 8, cy), fill=(90, 140, 200), width=1)
    d.line((cx, cy - r - 8, cx, cy + r + 8), fill=(90, 140, 200), width=1)
    draw_editorial_pill(d, w, h, "EDITORIAL ILLUSTRATION", accent=(230, 31, 45), fill=(14, 26, 46))
    return im


def make_illustration(width, height, category="GLOBAL NEWS", article=None):
    """Generate a story-specific, labelled editorial vector illustration.

    Tailors visual to news topic (Finance, Emergency, Tech, Leadership, Quote, Diplomacy)
    using pure Pillow vector graphics.
    """
    cat = str(category or "").upper()
    title = ""
    topic = ""
    if article and isinstance(article, dict):
        title = str(article.get("title") or "").lower()
        topic = str(article.get("classification", {}).get("topic") or "").lower()
        if article.get("quote_text"):
            cat = "QUOTE"

    combined = f"{cat} {topic} {title}".lower()

    if any(k in combined for k in ("quote", "statement", "remarks", "said", "testimony", "speech")):
        return render_quote_illustration(width, height)
    if any(k in combined for k in ("fire", "wildfire", "emergency", "disaster", "earthquake", "flood", "storm", "hurricane", "typhoon", "cyclone", "evacuation", "explosion", "blast", "tsunami", "volcano")):
        return render_crisis_illustration(width, height)
    if any(k in combined for k in ("business", "economy", "finance", "market", "trade", "stock", "banking", "inflation", "rate", "rates", "dollar", "treasury", "revenue", "gdp", "crypto")):
        return render_finance_illustration(width, height)
    if any(k in combined for k in ("technology", "tech", "science", "space", "artificial intelligence", "ai", "software", "cyber", "quantum", "semiconductor", "chip", "chips", "satellite", "spacewalk", "nasa")):
        return render_tech_illustration(width, height)
    if any(k in combined for k in ("diplomacy", "treaty", "sanctions", "sanction", "summit", "accord", "alliance", "united nations", "geopolitics", "international", "ambassador", "foreign", "icc", "icj")):
        label = "DIPLOMACY & SANCTIONS GRAPHIC" if any(s in combined for s in ("sanction", "sanctions", "icc", "icj")) else "GLOBAL AFFAIRS GRAPHIC"
        return render_diplomacy_illustration(width, height, label=label)
    if any(k in combined for k in ("leadership", "corporate", "government", "parliament", "congress", "senate", "court", "supreme", "legal", "policy", "regulator", "ministry", "minister", "president", "chancellor", "ceo")):
        return render_gov_illustration(width, height)
    return render_global_illustration(width, height)


def draw_photo_overlay(canvas, box, strength=155):
    x1, y1, x2, y2 = box
    h = y2 - y1
    overlay = Image.new("RGBA", (x2 - x1, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(h):
        alpha = int(strength * y / max(1, h - 1))
        od.line((0, y, x2 - x1, y), fill=(0, 0, 0, alpha))
    canvas.alpha_composite(overlay, (x1, y1))


def draw_footer(draw, source, date_x=700, y=1190, dark=True):
    fg = WHITE if dark else INK
    muted = MUTED if dark else (82, 96, 112)
    draw.line((42, y - 22, 1038, y - 22), fill=(100, 125, 155), width=2)
    draw.text((50, y), "NEWS SNAP", font=font(26, True), fill=RED)
    draw.text((230, y + 5), f"SOURCE  •  {source.upper()}", font=font(18, True), fill=fg)
    date = get_current_date_str("%d %b %Y").upper()
    draw.text((date_x, y + 38), date, font=font(17, True), fill=muted)


# ==============================================================================
# THE SIX APPROVED NEWS SNAP FORMAT RENDERERS
# ==============================================================================

def draw_template_01(article, post, photo):
    """Format 01: LIVE / DEVELOPING NEWS (Emergencies & Disasters)"""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (8, 14, 24, 255))
    crop_photo(canvas, photo, (0, 0, WIDTH, 840), category=emergency_event_label(str(article.get("title", ""))), article=article)
    # Soft cinematic vignette overlay so flames are visible while headline is 100% legible
    draw_photo_overlay(canvas, (0, 420, WIDTH, 840), 195)
    d = ImageDraw.Draw(canvas)

    # Brand and LIVE badge
    draw_brand_slash(d, 60, 48, scale=1.1)
    d.rounded_rectangle((245, 50, 375, 96), radius=15, fill=RED)
    d.ellipse((262, 67, 274, 79), fill=WHITE)
    d.text((284, 58), "LIVE", font=font(21, True), fill=WHITE)

    # Event label pill
    title = str(article.get("title", ""))
    badge = emergency_event_label(title)
    add_pill(d, (60, 470, 390, 526), badge, fill=RED, text_fill=WHITE, max_font=23)

    # White vertical accent line on left of headline
    d.rectangle((60, 545, 66, 755), fill=WHITE)

    # Two-tone headline: upper white, bottom yellow with shadow for maximum contrast
    headline = post["headline"].strip().upper()
    draw_two_tone_headline(d, headline, (82, 540, 1015, 765), accent_mode="bottom_yellow", max_size=58, min_size=36, max_lines=3, with_shadow=True)

    # Summary card: pure white rounded card
    d.rounded_rectangle((60, 795, 1020, 1215), radius=22, fill=WHITE)
    summary = summary_from_caption(post.get("caption", ""), 42)
    draw_wrapped(d, summary, (95, 830, 985, 1180), max_size=28, min_size=22, bold=False, fill=INK, max_lines=6, line_multiplier=1.28)

    # Standard footer
    draw_standard_footer(d, "GLOBAL NEWS", cta="DETAILS IN CAPTION →", y=1275, dark=True)
    return canvas


def draw_template_02(article, post, photo):
    """Format 02: BUSINESS & ECONOMY (Markets & Money)"""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (8, 16, 28, 255))
    d = ImageDraw.Draw(canvas)
    # Rounded dark navy card container
    d.rounded_rectangle((45, 30, 1035, 1320), radius=28, fill=(10, 24, 45), outline=(28, 52, 85), width=2)

    # Header: compass logo + date with globe
    draw_brand_compass(d, 75, 56, dark=True, scale=1.0)
    draw_globe_icon(d, 760, 75, r=12, color=WHITE)
    date_str = get_current_date_str("%d %b %Y").upper()
    d.text((782, 63), date_str, font=font(20, True), fill=WHITE)

    # Top photo card with rounded corners
    crop_photo(canvas, photo, (65, 125, 1015, 615), category="BUSINESS", article=article)
    d = ImageDraw.Draw(canvas)

    # Centered yellow BREAKING NEWS pill
    add_pill(d, (350, 580, 730, 650), "BREAKING NEWS", fill=YELLOW, text_fill=(0, 0, 0), max_font=26)

    # Two-tone headline: top line yellow, second line white
    headline = post["headline"].strip().upper()
    draw_two_tone_headline(d, headline, (85, 680, 995, 855), accent_mode="top_yellow", max_size=56, min_size=36, max_lines=3)

    # Summary in light blue-gray
    summary = validate_english_text(post["summary"].strip(), "summary") if post.get("summary") else summary_from_caption(post.get("caption", ""), 34)
    draw_wrapped(d, summary, (85, 875, 995, 1080), max_size=26, min_size=20, bold=False, fill=(210, 222, 235), max_lines=5, line_multiplier=1.24)

    # CTA pill button matching reference
    d.rounded_rectangle((75, 1120, 1005, 1220), radius=22, fill=WHITE, outline=(10, 24, 45), width=3)
    d.ellipse((120, 1145, 170, 1195), fill=(10, 24, 45))
    d.text((135, 1148), "→", font=font(26, True), fill=WHITE)
    draw_centered(d, (190, 1120, 890, 1220), "DETAILS IN CAPTION", font(26, True), (10, 24, 45))
    d.text((915, 1148), "→", font=font(26, True), fill=(10, 24, 45))
    return canvas


def draw_template_03(article, post, photo):
    """Format 03: PEOPLE & CORPORATE STORIES"""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (6, 12, 22, 255))
    crop_photo(canvas, photo, (0, 0, WIDTH, 890), category="PEOPLE", centering=(0.5, 0.22), article=article)
    # Convert photo area to monochrome / greyscale for dramatic portrait reference look
    box = (0, 0, WIDTH, 890)
    photo_crop = canvas.crop(box).convert("L").convert("RGBA")
    canvas.paste(photo_crop, (0, 0))
    draw_photo_overlay(canvas, (0, 460, WIDTH, 890), 220)
    d = ImageDraw.Draw(canvas)

    # Logo
    draw_brand_slash(d, 60, 48, scale=1.1)

    # Red BREAKING NEWS pill
    add_pill(d, (60, 545, 360, 605), "BREAKING NEWS", fill=RED, text_fill=WHITE, max_font=23)

    # Two-tone headline: white lines + yellow bottom line with shadow
    headline = post["headline"].strip().upper()
    draw_two_tone_headline(d, headline, (60, 625, 1020, 860), accent_mode="bottom_yellow", max_size=58, min_size=36, max_lines=3, with_shadow=True)

    # Clean white summary
    summary = summary_from_caption(post.get("caption", ""), 32)
    draw_wrapped(d, summary, (60, 880, 1020, 1055), max_size=26, min_size=20, bold=False, fill=WHITE, max_lines=4, line_multiplier=1.22)

    # Dynamic category pills strictly matching the article (no hardcoded tags)
    pills = extract_matching_category_tags(article)
    px = 60
    for label, col in pills:
        bbox = d.textbbox((0, 0), label, font=font(19, True))
        pw = max(130, bbox[2] - bbox[0] + 32)
        d.rounded_rectangle((px, 1090, px + pw, 1145), radius=16, fill=col)
        draw_centered(d, (px, 1090, px + pw, 1145), label, font(19, True), WHITE)
        px += pw + 16

    topic = str(article.get("classification", {}).get("topic", "CORPORATE NEWS")).upper()
    draw_standard_footer(d, topic[:18], cta="DETAILS IN CAPTION →", y=1275, dark=True)
    return canvas


def load_roundup():
    roundup_path, post_path = Path("roundup.json"), Path("roundup_post.json")
    if not roundup_path.is_file() or not post_path.is_file():
        raise ValueError("Format 04 needs both roundup.json and roundup_post.json")
    roundup = json.loads(roundup_path.read_text(encoding="utf-8"))
    post = json.loads(post_path.read_text(encoding="utf-8"))
    stories = roundup.get("stories", [])
    if not isinstance(stories, list) or len(stories) != 3:
        raise ValueError("Format 04 requires exactly 3 verified stories")
    for i, story in enumerate(stories, start=1):
        story["title"] = validate_english_text(story.get("title"), f"roundup story {i}", 4, 14)
        if not story.get("domain") or not story.get("url"):
            raise ValueError(f"Roundup story {i} lacks source information")
        story["summary"] = validate_english_text(story.get("summary"), f"roundup summary {i}", 6, 25)
    post["headline"] = validate_english_text(post.get("headline"), "roundup headline", 3, 10)
    return stories, post


def draw_template_04(article, roundup_post, stories, photos):
    """Format 04: DAILY HEADLINES / ROUNDUP (Multiple Stories)"""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (8, 20, 38, 255))
    d = ImageDraw.Draw(canvas)

    # Subtle grid
    for gx in range(0, WIDTH, 120):
        d.line((gx, 0, gx, HEIGHT), fill=(12, 28, 52), width=1)
    for gy in range(0, HEIGHT, 120):
        d.line((0, gy, WIDTH, gy), fill=(12, 28, 52), width=1)

    # Header
    draw_brand_slash(d, 50, 42, scale=1.0)
    # Calendar icon + date
    date_str = get_current_date_str("%d %b %Y").upper()
    d.rectangle((740, 56, 762, 78), outline=WHITE, width=2)
    d.line((740, 64, 762, 64), fill=WHITE, width=2)
    d.text((774, 54), date_str, font=font(19, True), fill=WHITE)

    # Title section
    d.text((55, 125), "TODAY'S", font=font(48, True), fill=WHITE)
    # Red parallelogram ribbon
    d.polygon([(50, 275), (70, 195), (650, 195), (630, 275)], fill=RED)
    d.text((80, 202), "HEADLINES", font=font(56, True), fill=WHITE)
    # Red pill TOP 3 STORIES
    add_pill(d, (695, 205, 1025, 268), "TOP 3 STORIES", fill=RED, text_fill=WHITE, max_font=22)

    # 3 slanted white story rows
    y = 310
    for idx, (story, photo) in enumerate(zip(stories, photos), start=1):
        d.polygon([(65, y + 215), (85, y), (1025, y), (1005, y + 215)], fill=WHITE)
        crop_photo(canvas, photo, (85, y + 8, 325, y + 207), category=category_label(story), article=story)
        d = ImageDraw.Draw(canvas)
        # Red numbered trapezoid badge
        d.polygon([(305, y + 155), (320, y + 55), (395, y + 55), (380, y + 155)], fill=RED)
        draw_centered(d, (305, y + 55, 395, y + 155), f"{idx:02d}", font(32, True), WHITE)
        # Story title
        draw_wrapped(d, story["title"].upper(), (415, y + 15, 990, y + 115), max_size=26, min_size=18, bold=True, fill=(11, 27, 51), max_lines=2)
        # Story summary
        story_summary = summary_from_caption(story.get("summary", story["title"]), 22)
        draw_wrapped(d, story_summary, (415, y + 118, 990, y + 205), max_size=18, min_size=15, bold=False, fill=(70, 80, 95), max_lines=3, line_multiplier=1.16)
        y += 235

    # Bottom notification banner
    d.rounded_rectangle((50, 1025, 1030, 1225), radius=24, fill=RED)
    d.ellipse((75, 1085, 145, 1155), outline=WHITE, width=3)
    d.text((95, 1098), "●", font=font(24, False), fill=WHITE)
    d.text((165, 1090), "Stay updated with the latest", font=font(22, True), fill=WHITE)
    d.text((165, 1125), "developments from around the world.", font=font(20, False), fill=WHITE)
    add_pill(d, (570, 1075, 1005, 1165), "FOLLOW NEWS SNAP FOR DAILY NEWS →", fill=(195, 20, 32), text_fill=WHITE, max_font=18)

    # Footer
    d.text((50, 1270), "NEWS SNAP  •  GLOBAL NEWS", font=font(22, True), fill=WHITE)
    d.text((660, 1272), "REFERENCE VISUALS; CREDITS IN CAPTION", font=font(14, True), fill=YELLOW)
    return canvas


def draw_template_05(article, post, photo):
    """Format 05: SINGLE-STORY NEWS REPORT (Detailed Update)"""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (6, 12, 22, 255))
    d = ImageDraw.Draw(canvas)
    # Inner white card with rounded corners
    d.rounded_rectangle((45, 30, 1035, 1320), radius=26, fill=WHITE)

    # Brand logo top left
    draw_brand_compass(d, 75, 54, dark=False, scale=1.0)

    # Red header ribbon: BREAKING NEWS with 3 white hazard stripes
    d.rounded_rectangle((75, 125, 1005, 205), radius=10, fill=RED)
    d.text((110, 142), "BREAKING NEWS", font=font(44, True), fill=WHITE)
    for sx in (860, 905, 950):
        d.polygon([(sx, 130), (sx + 24, 130), (sx - 10, 200), (sx - 34, 200)], fill=WHITE)

    # Framed rectangular photo
    crop_photo(canvas, photo, (75, 230, 1005, 650), category=category_label(article), article=article)
    d = ImageDraw.Draw(canvas)

    # Red vertical accent line
    d.rectangle((75, 680, 83, 1110), fill=RED)

    # Date line
    date_str = get_current_date_str("%A, %d %B %Y")
    d.text((105, 682), date_str, font=font(21, False), fill=(90, 95, 105))

    # Bold black uppercase headline
    headline = post["headline"].strip().upper()
    draw_two_tone_headline(d, headline, (105, 720, 995, 880), accent_mode="all_black", max_size=46, min_size=32, max_lines=3)

    # Detailed summary
    summary = summary_from_caption(post.get("caption", ""), 52)
    draw_wrapped(d, summary, (105, 895, 995, 1130), max_size=26, min_size=20, bold=False, fill=(40, 45, 55), max_lines=7, line_multiplier=1.24)

    # Dark navy bottom footer bar inside the card
    d.rounded_rectangle((45, 1205, 1035, 1320), radius=26, fill=(10, 24, 45))
    d.rectangle((45, 1205, 1035, 1240), fill=(10, 24, 45))
    draw_globe_icon(d, 85, 1262, r=13, color=WHITE)
    d.text((112, 1250), "NEWS SNAP  |  WORLD NEWS", font=font(22, True), fill=WHITE)
    return canvas


def draw_template_06(article, post, photo):
    """Format 06: QUOTES & PUBLIC STATEMENTS"""
    if article.get("quote_verified") is not True:
        raise ValueError(
            "Format 06 REFUSAL: Quotation cannot be verified from original source (quote_verified is not True). "
            "Never present unverified or rewritten quotations inside quotation marks. "
            "Skip Format 06 and use an appropriate non-quote format instead."
        )
    quote = validate_english_text(article.get("quote_text"), "verified quotation", 5, 45)
    speaker = validate_english_text(article.get("speaker"), "speaker name", 1, 8)

    # Textured deep emerald canvas
    canvas = gradient(top=(7, 52, 39), bottom=(4, 32, 25))

    # Place verified speaker portrait on right side FIRST (so torn paper overlaps it cleanly)
    crop_photo(canvas, photo, (500, 190, 1030, 1190), category="PEOPLE", centering=(0.5, 0.22), article=article)

    # Draw soft drop shadow behind torn paper edge
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    torn_pts = [(50, 190)]
    jagged_x = [600, 588, 618, 592, 622, 586, 615, 590, 620, 594, 612, 585, 608, 580]
    step_y = (1190 - 190) / (len(jagged_x) - 1)
    for j_idx, jx in enumerate(jagged_x):
        torn_pts.append((jx, int(190 + j_idx * step_y)))
    torn_pts.extend([(50, 1190)])
    shadow_pts = [(px + 8, py + 4) for (px, py) in torn_pts]
    od.polygon(shadow_pts, fill=(0, 0, 0, 110))
    canvas.alpha_composite(overlay)

    d = ImageDraw.Draw(canvas)
    # White torn paper sheet
    d.polygon(torn_pts, fill=(250, 250, 245))

    # Header: Red slash logo
    draw_brand_slash(d, 60, 48, scale=1.1)

    d = ImageDraw.Draw(canvas)
    # Large quotation marks
    d.text((85, 260), "“", font=font(115, True), fill=(27, 94, 57))

    # Verbatim quote text
    formatted_quote = f"'{quote.strip('\"\'')}'"
    draw_wrapped(d, formatted_quote, (95, 380, 570, 790), max_size=36, min_size=23, bold=True, fill=(18, 30, 24), max_lines=8, line_multiplier=1.2)

    # Speaker pill
    add_pill(d, (95, 825, 540, 895), speaker, fill=(30, 126, 52), text_fill=WHITE, max_font=26)

    # Speaker role
    role = str(article.get("speaker_role", "")).strip()
    if role:
        role = validate_english_text(role, "speaker role", 1, 10)
        draw_wrapped(d, role, (98, 915, 550, 1020), max_size=22, min_size=16, bold=False, fill=(45, 65, 52), max_lines=3)

    # Standardized bottom footer
    draw_standard_footer(d, "WORLD NEWS", cta="DETAILS IN CAPTION →", y=1275, dark=True)
    return canvas


def annotate_image_credit(post, photo_info, caption_path="post.json", story_index=None):
    if not photo_info:
        return
    caption = str(post.get("caption", "")).strip()
    if photo_info["page_url"] in caption:
        return

    story_prefix = f"Story {story_index} " if story_index else ""
    credit_parts = [
        f"{story_prefix}Image credit: {photo_info['title']} by {photo_info['artist']}.",
        f"Licence: {photo_info['license']}.",
    ]
    if photo_info.get("license_url"):
        credit_parts.append(f"Licence terms: {photo_info['license_url']}")
    credit_parts.append(f"Source file: {photo_info['page_url']}")
    credit_parts.append("Changes: cropped/resized and combined with NEWS SNAP text and graphics.")
    credit = "\n\n" + " ".join(credit_parts)

    updated = caption + credit
    if len(updated) > 2200:
        raise ValueError("Caption plus required image attribution exceeds 2,200 characters; refusing output")
    post["caption"] = updated
    Path(caption_path).write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")


def render_approved_format(template_id, article, post):
    """Render the exact approved format (01-06) from the format registry."""
    if template_id not in FORMAT_REGISTRY:
        raise ValueError(f"Unrecognized format {template_id}. Must be one of {list(FORMAT_REGISTRY.keys())}")

    if template_id == "04":
        stories, roundup_post = load_roundup()
        photos = [query_commons_image(s) for s in stories]
        image = draw_template_04(article, roundup_post, stories, photos)
        return image, roundup_post, photos

    if template_id == "06":
        if article.get("quote_verified") is not True or not article.get("quote_text") or not article.get("speaker"):
            raise ValueError(
                "Format 06 REFUSAL: Quotation cannot be verified from original source (quote_verified is not True). "
                "Never present unverified or rewritten quotations inside quotation marks. "
                "Skip Format 06 and use an appropriate non-quote format instead."
            )
        photo = query_commons_image(article.get("speaker", ""), require_all_terms=True)
    else:
        photo = query_commons_image(article)

    if template_id == "01":
        image = draw_template_01(article, post, photo)
    elif template_id == "02":
        image = draw_template_02(article, post, photo)
    elif template_id == "03":
        image = draw_template_03(article, post, photo)
    elif template_id == "05":
        image = draw_template_05(article, post, photo)
    elif template_id == "06":
        image = draw_template_06(article, post, photo)
    else:
        raise ValueError(f"Unknown NEWS SNAP template: {template_id}")

    return image, post, [photo]


def main():
    post_path = Path("post.json")
    article_path = Path("selected_article.json")
    if not post_path.is_file() or not article_path.is_file():
        print("[INFO] post.json or selected_article.json missing. Skipping image generation.")
        return

    post = json.loads(post_path.read_text(encoding="utf-8"))
    article = json.loads(article_path.read_text(encoding="utf-8"))

    # Determine format using the format registry
    roundup_exists = Path("roundup.json").is_file() and Path("roundup_post.json").is_file()
    template_id = os.environ.get("NEWS_SNAP_FORCE_TEMPLATE")
    if template_id:
        template_id = template_id.zfill(2)
        if template_id not in FORMAT_REGISTRY:
            raise ValueError(f"NEWS_SNAP_FORCE_TEMPLATE must be one of {list(FORMAT_REGISTRY.keys())}")
        selection_reason = f"Forced via environment variable: Format {template_id} ({FORMAT_REGISTRY[template_id]['name']})"
    else:
        template_id, selection_reason = classify_format_for_article(article, roundup_exists)

    if template_id == "06" and not (article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker")):
        print("[WARN] Format 06 skipped: quote is not source-verified (quote_verified is not True). Using appropriate non-quote format instead.")
        clean_article = dict(article)
        clean_article.pop("quote_text", None)
        clean_article.pop("quote_verified", None)
        template_id, selection_reason = classify_format_for_article(clean_article, roundup_exists)

    format_info = FORMAT_REGISTRY[template_id]
    print(f"Format Selected: Format {template_id} — {format_info['name']}")
    print(f"Selection Reason: {selection_reason}")

    if template_id == "04":
        roundup_post = json.loads(Path("roundup_post.json").read_text(encoding="utf-8"))
        post_for_render = roundup_post
        post_for_render["headline"] = validate_english_text(post_for_render.get("headline"), "roundup headline", 3, 12)
    else:
        post_for_render = post
        post_for_render["headline"] = validate_english_text(post_for_render.get("headline"), "headline", 4, 14)

    source = str(article.get("domain", "")).strip().lower()
    if not source or not re.fullmatch(r"[a-z0-9.-]+", source):
        raise ValueError("Invalid publisher domain; refusing image")

    image, rendered_post, photo_infos = render_approved_format(template_id, article, post_for_render)
    rendered_post["format"] = template_id
    if template_id == "04":
        for idx, info in enumerate(photo_infos, start=1):
            if info:
                annotate_image_credit(rendered_post, info, caption_path="post.json", story_index=idx)
        Path("roundup_post.json").write_text(json.dumps(rendered_post, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        for info in photo_infos:
            if info:
                annotate_image_credit(rendered_post, info, caption_path="post.json")
    Path("post.json").write_text(json.dumps(rendered_post, ensure_ascii=False, indent=2), encoding="utf-8")

    image = image.convert("RGB")
    image.save(OUTPUT, "JPEG", quality=95, optimize=True)

    with Image.open(OUTPUT) as check:
        if check.size != (WIDTH, HEIGHT) or check.format != "JPEG":
            raise ValueError("Exported image failed format/dimension validation")
        if OUTPUT.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Image exceeds 8 MB")

    print(f"\nNEWS SNAP post created: {OUTPUT}")
    print(f"Template: {template_id}")
    print(f"Format Name: {format_info['name']}")
    print(f"Dimensions: {WIDTH}x{HEIGHT}")
    print(f"Source: {source}")


if __name__ == "__main__":
    main()

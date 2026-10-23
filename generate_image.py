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
import sys
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


def font(size, bold=False, condensed=False):
    """Load robust, high-quality system font across Ubuntu, Windows, and macOS."""
    if condensed and bold:
        candidates = [
            r"C:\Windows\Fonts\arialnb.ttf",
            r"C:\Windows\Fonts\impact.ttf",
            r"C:\Windows\Fonts\trebucbd.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            "DejaVuSans-Bold.ttf",
            "Arial-Bold.ttf",
        ]
    elif bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            "DejaVuSans-Bold.ttf",
            "Arial-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "DejaVuSans.ttf",
            "Arial.ttf",
        ]
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
        if not predictions:
            return True
        if predictions[0].lang == "en" and predictions[0].prob >= minimum_confidence:
            return True
        en_prob = next((p.prob for p in predictions if p.lang == "en"), 0.0)
        if en_prob >= 0.25:
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
                "news", "first", "more", "over", "under", "deal", "plan", "sanctions",
                "is", "are", "was", "were", "has", "had", "close", "amid", "talks"
            }
            tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z]{2,}\b", text)]
            matches = sum(1 for w in tokens if w in common_english)
            if matches >= 2 or (len(tokens) <= 5 and matches >= 1):
                return True
    except Exception:
        return True
    return False


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


def draw_two_tone_headline(draw, text, box, accent_mode="bottom_yellow", max_size=64, min_size=34, max_lines=4, with_shadow=False):
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1

    best_size = min_size
    best_lines = [text]
    for sz in range(max_size, min_size - 1, -2):
        ft = font(sz, bold=True, condensed=True)
        lines = wrap(draw, text, ft, max_w)
        line_h = int(sz * 1.15)
        if len(lines) <= max_lines and len(lines) * line_h <= max_h:
            best_size = sz
            best_lines = lines
            break

    ft = font(best_size, bold=True, condensed=True)
    line_h = int(best_size * 1.15)
    curr_y = y1

    for idx, line in enumerate(best_lines):
        if accent_mode == "top_yellow":
            col = YELLOW if idx == 0 else WHITE
        elif accent_mode == "bottom_yellow":
            col = YELLOW if idx == len(best_lines) - 1 else WHITE
        elif accent_mode == "bottom_red":
            col = RED if idx == len(best_lines) - 1 else WHITE
        elif accent_mode == "all_black":
            col = INK
        elif accent_mode == "all_white":
            col = WHITE
        else:
            col = WHITE
        if with_shadow and col != INK:
            for sx, sy in ((3, 3), (2, 2), (1, 1), (-1, 1), (1, -1)):
                draw.text((x1 + sx, curr_y + sy), line, font=ft, fill=(0, 0, 0, 240))
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
    "issues", "issue", "leads", "lead", "holds", "hold",
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


BROAD_GEOGRAPHIC_TERMS = {
    "california", "texas", "florida", "york", "washington", "london", "paris",
    "berlin", "tokyo", "beijing", "moscow", "delhi", "mumbai", "chicago",
    "america", "american", "us", "usa", "uk", "britain", "british", "france",
    "french", "germany", "german", "india", "indian", "china", "chinese",
    "russia", "russian", "canada", "canadian", "australia", "australian",
    "japan", "japanese", "europe", "european", "asia", "asian", "africa",
    "african", "state", "states", "nation", "nations", "national", "federal",
    "international", "global", "local", "regional", "city", "county",
    "district", "province", "country"
}

GENERIC_ROLE_AND_ADMIN_TERMS = {
    "official", "officials", "leader", "leaders", "authority", "authorities",
    "spokesperson", "spokesman", "spokeswoman", "representative", "representatives",
    "member", "members", "person", "people", "staff", "worker", "workers",
    "meeting", "meet", "meets", "conference", "briefing", "press", "announcement",
    "board", "panel", "committee", "agency", "department", "ministry",
    "government", "administration", "office", "group", "public", "service",
    "event", "discussion", "talks", "report", "update", "new"
}

BROAD_TERMS = BROAD_GEOGRAPHIC_TERMS | GENERIC_ROLE_AND_ADMIN_TERMS

DISASTER_EMERGENCY_TERMS = {
    "fema", "federal emergency management agency", "disaster", "disasters",
    "disaster relief", "disaster assistance", "emergency management",
    "search and rescue", "wildfire", "wildfires", "firefighter", "firefighters",
    "fire department", "flood waters", "flood relief", "hurricane relief",
    "earthquake relief", "casualty", "casualties", "military combat"
}


def is_photo_meaningfully_relevant(title: str, description: str, article: dict, query_terms=None) -> tuple[bool, str]:
    """Validate whether candidate photo title/description meaningfully matches the article topic and entities.

    Rejects:
    1. Disaster/FEMA assistance imagery for election, ballot, or non-disaster stories.
    2. Candidates whose only matches with the article/query are broad geographic or generic role terms (e.g. "California", "officials").
    3. Candidates lacking meaningful semantic overlap with the specific entities or topic.

    Returns (is_relevant, reason).
    """
    if not isinstance(article, dict):
        return True, "No article context provided"

    art_title = str(article.get("title", "")).lower()
    art_topic = str(article.get("classification", {}).get("topic", "")).lower()
    art_summary = str(article.get("summary", "") or article.get("description", "")).lower()
    art_speaker = str(article.get("speaker", "")).lower()
    art_combined = f"{art_title} {art_topic} {art_summary} {art_speaker}"

    cand_text = f"{title} {description}".lower()
    cand_tokens = set(re.findall(r"[a-z0-9]+", cand_text))

    # Check 1: Election & ballot stories must NEVER use disaster/FEMA imagery
    is_election_story = any(w in art_combined for w in (
        "ballot", "ballots", "election", "elections", "voting", "vote", "votes",
        "polling", "poll", "polls", "electoral", "primary", "referendum", "precinct"
    ))
    if is_election_story:
        found_disaster = [d for d in DISASTER_EMERGENCY_TERMS if d in cand_text]
        if found_disaster:
            return False, f"Election/ballot story cannot use disaster/FEMA imagery (matched '{found_disaster[0]}')"

    # Check 2: Non-disaster stories should not use FEMA disaster assistance imagery
    is_disaster_story = any(w in art_combined for w in (
        "wildfire", "fire", "flood", "flooding", "earthquake", "quake", "tsunami",
        "hurricane", "cyclone", "typhoon", "tornado", "landslide", "disaster", "evacuation"
    ))
    if not is_disaster_story:
        if "fema" in cand_tokens or "federal emergency management agency" in cand_text:
            return False, "Non-disaster story cannot use FEMA disaster assistance imagery"

    # Check 3: Legal, sanctions, and court stories (e.g. ICC, ICJ, war crimes, prosecutor) must NEVER use commercial skyscraper or sports imagery
    is_court_story = any(w in art_combined for w in (
        "international criminal court", "icc", "icj", "international court of justice",
        "war crimes", "prosecutor", "the hague", "tribunal"
    ))
    if is_court_story:
        court_conflicts = (
            "commerce centre", "hong kong", "kowloon", "skyscraper",
            "tallest building", "commercial building", "office tower", "shopping mall",
            "cricket", "stadium", "champions trophy", "bcci"
        )
        for cc in court_conflicts:
            if cc in cand_text:
                return False, f"Legal/court story cannot use commercial skyscraper or sports imagery (matched '{cc}')"

    # Check 4: Rejection of broad-terms-only matches
    raw_art_tokens = set(re.findall(r"[a-z0-9]+", art_combined))
    meaningful_art_tokens = {
        w for w in raw_art_tokens
        if len(w) >= 3 and w not in STOP_WORDS and w not in GENERIC_HEADLINE_VERBS
    }
    query_tokens = set(query_terms) if query_terms else set()
    specific_art_tokens = {w for w in (meaningful_art_tokens | query_tokens) if w not in BROAD_TERMS}

    if specific_art_tokens:
        overlap_with_article = cand_tokens.intersection(meaningful_art_tokens | query_tokens)
        if not overlap_with_article:
            return False, "Candidate shares no meaningful keywords with article"
        if overlap_with_article.issubset(BROAD_TERMS):
            matched_broad = ", ".join(sorted(overlap_with_article))
            return False, f"Candidate matches only broad generic/geographic terms ({matched_broad}) with no specific topic/entity match"

    return True, "Candidate photo is meaningfully relevant to story"


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

    tokens = [w for w in re.findall(r"[A-Za-z0-9]+", title) if len(w) >= 3]
    salient = [w for w in tokens if w.lower() not in GENERIC_HEADLINE_VERBS and w.lower() not in STOP_WORDS]
    specific_salient = [w for w in salient if w.lower() not in BROAD_TERMS]

    for ch in chunks:
        ch_tokens = ch.split()
        if 2 <= len(ch_tokens) <= 4:
            if all(t.lower() in BROAD_TERMS for t in ch_tokens):
                if specific_salient:
                    augmented = f"{ch} {specific_salient[0]}"
                    if augmented not in queries:
                        queries.append(augmented)
            else:
                if ch not in queries and ch.lower() not in {"breaking news", "live update", "daily briefing"}:
                    queries.append(ch)

    # 6. Salient nouns from headline without action verbs or stop words
    if len(salient) >= 2:
        if all(t.lower() in BROAD_TERMS for t in salient[:2]) and specific_salient:
            queries.append(f"{salient[0]} {specific_salient[0]}")
        else:
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

            # Check semantic and topic relevance to article
            is_rel, rel_reason = is_photo_meaningfully_relevant(title, description, query_or_article, query_terms)
            if not is_rel:
                print(f"Photo sourcing: rejected candidate '{title}': {rel_reason}.")
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


def query_commons_images(query_or_article, max_images=2):
    """Query Wikimedia Commons for up to max_images distinct, verified, permitted photographs.

    Enforces strict factual relevance, permitted licenses (CC BY, CC BY-SA, CC0, PD),
    and no conflicting entities. Returns a list of photo dicts (0, 1, or 2).
    """
    if os.environ.get("NEWS_SNAP_OFFLINE_PREVIEW") == "1":
        return []

    if max_images <= 1:
        single = query_commons_image(query_or_article)
        return [single] if single else []

    candidate_queries = []
    if isinstance(query_or_article, dict):
        candidate_queries = build_photo_search_queries(query_or_article)
    elif isinstance(query_or_article, str) and query_or_article.strip():
        candidate_queries = [query_or_article.strip()]

    if not candidate_queries:
        return []

    photos = []
    seen_urls = set()

    # 1. Search for primary hero photograph
    primary = query_commons_image(query_or_article)
    if primary and primary.get("page_url"):
        photos.append(primary)
        seen_urls.add(primary["page_url"])

    # 2. If collage requested and multiple queries exist, search for distinct secondary photograph
    if len(photos) < max_images and len(candidate_queries) >= 2:
        for secondary_query in candidate_queries[1:]:
            tokens = [t.lower() for t in secondary_query.split()]
            if len(tokens) < 2:
                continue
            if all(t in BROAD_TERMS or t in STOP_WORDS or t in GENERIC_HEADLINE_VERBS for t in tokens):
                continue
            sec = query_commons_image(secondary_query)
            if sec and sec.get("page_url") and sec["page_url"] not in seen_urls:
                photos.append(sec)
                seen_urls.add(sec["page_url"])
                print(f"Photo sourcing: accepted secondary collage photo for '{secondary_query}'.")
                break

    return photos


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


def determine_photo_label(photo_info: dict, article: dict = None) -> str:
    """Determine the accurate visual label for a photograph inside the photo area.

    - Returns 'FILE PHOTO' only when the source supports that description (e.g. metadata/title/description
      explicitly indicates file photo, archive, archival image, etc.).
    - Returns 'CONTEXTUAL IMAGE' for relevant licensed photographs not verified as depicting the exact event.
    - Never infers that a photograph depicts the exact event merely because subject, location, or people match.
    """
    if not photo_info or not isinstance(photo_info, dict):
        return ""

    if photo_info.get("event_verified") is True:
        return ""

    # Check if source text or metadata explicitly supports 'FILE PHOTO'
    source_indicators = []
    for key in ("title", "description", "artist", "source", "notes"):
        val = photo_info.get(key)
        if val:
            source_indicators.append(str(val))

    combined_source_text = " ".join(source_indicators).lower()

    file_photo_cues = (
        "file photo", "file picture", "file image", "file-photo",
        "archive photo", "archival photo", "archive image", "archival image",
        "stock photo", "historical photo", "undated file photo", "archive file"
    )

    if photo_info.get("is_file_photo") is True or any(cue in combined_source_text for cue in file_photo_cues):
        return "FILE PHOTO"

    return "CONTEXTUAL IMAGE"


def draw_photo_label(canvas, box, text, position="top_right"):
    """Overlay a small, readable photo label badge (e.g. 'CONTEXTUAL IMAGE' or 'FILE PHOTO') inside the photo area.

    Placed cleanly inside the photo boundaries without shifting or redesigning any layout elements.
    """
    if not text:
        return

    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1

    is_thumbnail = (w < 350 or h < 300)
    font_size = 11 if is_thumbnail else 14
    f = font(font_size, bold=True)

    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_h = 7 if is_thumbnail else 12
    pad_v = 4 if is_thumbnail else 6
    pw = tw + pad_h * 2
    ph = th + pad_v * 2

    margin_x = 8 if is_thumbnail else (24 if x1 == 0 else 18)
    margin_y = 8 if is_thumbnail else (96 if y1 == 0 else 16)

    if position == "top_left":
        px1 = x1 + margin_x
        py1 = y1 + margin_y
    elif position == "bottom_right":
        px1 = x2 - pw - margin_x
        py1 = y2 - ph - margin_y
    else:  # default "top_right"
        px1 = x2 - pw - margin_x
        py1 = y1 + margin_y

    px2 = px1 + pw
    py2 = py1 + ph

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    radius = max(6, ph // 2)
    d.rounded_rectangle((px1, py1, px2, py2), radius=radius, fill=(8, 14, 24, 225), outline=(230, 240, 255, 180), width=1)

    text_x = px1 + (pw - tw) // 2 - bbox[0]
    text_y = py1 + (ph - th) // 2 - bbox[1]
    d.text((text_x, text_y), text, font=f, fill=(255, 255, 255, 255))

    canvas.alpha_composite(overlay)


def crop_photo(canvas, photo_info, box, category="GLOBAL NEWS", centering=(0.5, 0.5), article=None, draw_label=True, label_position="top_right"):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if photo_info and isinstance(photo_info.get("image"), Image.Image):
        try:
            photo = ImageOps.fit(photo_info["image"], (w, h), method=Image.Resampling.LANCZOS, centering=centering)
            canvas.paste(photo.convert("RGBA"), (x1, y1))
            if draw_label:
                lbl = determine_photo_label(photo_info, article)
                if lbl:
                    draw_photo_label(canvas, box, lbl, position=label_position)
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
    draw_editorial_pill(d, w, h, "FINANCIAL ILLUSTRATION", accent=(255, 207, 45), fill=(10, 24, 45))
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
    draw_editorial_pill(d, w, h, "EMERGENCY ILLUSTRATION", accent=(230, 31, 45), fill=(28, 12, 16))
    return im


def render_diplomacy_illustration(w, h, label="GLOBAL AFFAIRS ILLUSTRATION"):
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
    draw_editorial_pill(d, w, h, "TECHNOLOGY ILLUSTRATION", accent=(100, 210, 255), fill=(8, 20, 36))
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


def render_election_illustration(w, h):
    """Render a neutral ballot, polling-place, or election-administration visual clearly labelled as an illustration."""
    im, d = create_vector_gradient(w, h, (12, 26, 48), (6, 14, 28))
    cx, cy = w // 2, int(h * 0.44)

    # Box dimensions scaled to canvas
    bw = int(min(w * 0.52, h * 0.58))
    bh = int(bw * 0.72)

    box_left = cx - bw // 2
    box_right = cx + bw // 2
    box_top = cy - int(bh * 0.15)
    box_bot = cy + int(bh * 0.75)

    # Ballot Box Body
    d.rounded_rectangle((box_left, box_top, box_right, box_bot), radius=16, fill=(18, 34, 62), outline=(70, 130, 215), width=2)

    # Ballot slot on top lid
    slot_w = int(bw * 0.60)
    slot_h = max(4, int(bh * 0.05))
    d.rounded_rectangle((cx - slot_w // 2, box_top - slot_h // 2, cx + slot_w // 2, box_top + slot_h // 2), radius=slot_h // 2, fill=(6, 12, 22), outline=(50, 95, 165), width=1)

    # Official ballot paper slip entering the slot
    slip_w = int(slot_w * 0.75)
    slip_h = int(bh * 0.70)
    slip_left = cx - slip_w // 2
    slip_right = cx + slip_w // 2
    slip_top = box_top - int(slip_h * 0.65)
    slip_bot = box_top + int(slip_h * 0.35)

    # Drop shadow behind ballot slip
    d.rectangle((slip_left + 4, slip_top + 4, slip_right + 4, slip_bot + 4), fill=(10, 18, 32))

    # Ballot paper (crisp official white paper)
    d.rectangle((slip_left, slip_top, slip_right, slip_bot), fill=(244, 248, 255), outline=(190, 210, 235), width=1)

    # Ballot choice lines and checkmark on the visible upper slip
    line_y_start = slip_top + int(slip_h * 0.12)
    line_spacing = max(8, int(slip_h * 0.12))
    for i in range(3):
        ly = line_y_start + i * line_spacing
        if ly < box_top - 6:
            # Checkbox
            cb_size = max(6, int(slip_w * 0.09))
            cb_x = slip_left + int(slip_w * 0.10)
            d.rectangle((cb_x, ly - cb_size // 2, cb_x + cb_size, ly + cb_size // 2), outline=(120, 140, 170), width=1)
            if i == 0:
                # Cast vote checkmark in the first box
                d.line((cb_x + 2, ly, cb_x + cb_size // 2, ly + cb_size // 2 - 1), fill=(40, 160, 90), width=2)
                d.line((cb_x + cb_size // 2, ly + cb_size // 2 - 1, cb_x + cb_size + 2, ly - cb_size // 2), fill=(40, 160, 90), width=2)
            # Ballot text lines
            d.line((cb_x + cb_size + 8, ly, slip_right - int(slip_w * 0.10), ly), fill=(150, 165, 185), width=2)

    # Front emblem / seal on the ballot box
    emblem_r = int(bw * 0.16)
    emblem_y = (box_top + box_bot) // 2 + int(bh * 0.08)
    d.ellipse((cx - emblem_r, emblem_y - emblem_r, cx + emblem_r, emblem_y + emblem_r), fill=(24, 44, 78), outline=(70, 130, 215), width=2)

    # Stylized checkmark emblem inside circle
    ck_size = int(emblem_r * 0.55)
    d.line((cx - ck_size // 2, emblem_y, cx - ck_size // 6, emblem_y + ck_size // 2), fill=(255, 207, 45), width=3)
    d.line((cx - ck_size // 6, emblem_y + ck_size // 2, cx + ck_size // 2 + 2, emblem_y - ck_size // 2), fill=(255, 207, 45), width=3)

    # Clear visible illustration label
    draw_editorial_pill(d, w, h, "ELECTION & BALLOT ILLUSTRATION", accent=(70, 140, 220), fill=(12, 26, 48))
    return im


def render_health_illustration(w, h):
    """Render a clean, scientific and dignified public-health illustration without frightening imagery."""
    import math
    im, d = create_vector_gradient(w, h, (6, 28, 38), (4, 14, 22))
    cx, cy = w // 2, int(h * 0.44)
    r = int(min(w, h) * 0.32)
    # Clean medical cross / health research emblem
    cw = max(16, int(r * 0.35))
    ch = max(45, int(r * 0.95))
    d.rounded_rectangle((cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2), radius=cw // 4, fill=(16, 85, 95), outline=(45, 212, 191), width=2)
    d.rounded_rectangle((cx - ch // 2, cy - cw // 2, cx + ch // 2, cy + cw // 2), radius=cw // 4, fill=(16, 85, 95), outline=(45, 212, 191), width=2)
    # Subtle circular orbit ring
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(30, 110, 120), width=1)
    # Scientific data nodes along the perimeter
    for ang in range(0, 360, 45):
        rad = math.radians(ang)
        nx = int(cx + r * math.cos(rad))
        ny = int(cy + r * math.sin(rad))
        d.line((cx, cy, nx, ny), fill=(20, 65, 75), width=1)
        d.ellipse((nx - 4, ny - 4, nx + 4, ny + 4), fill=(45, 212, 191), outline=(255, 255, 255), width=1)
    draw_editorial_pill(d, w, h, "PUBLIC HEALTH & SCIENCE RESEARCH", accent=(45, 212, 191), fill=(6, 28, 38))
    return im


def make_illustration(width, height, category="GLOBAL NEWS", article=None):
    """Generate a story-specific, labelled editorial vector illustration.

    Tailors visual to news topic (Finance, Emergency, Health, Tech, Leadership, Quote, Diplomacy, Election)
    using pure Pillow vector graphics.
    """
    cat = str(category or "").upper()
    title = ""
    topic = ""
    summary = ""
    if article and isinstance(article, dict):
        title = str(article.get("title") or "").lower()
        topic = str(article.get("classification", {}).get("topic") or "").lower()
        summary = str(article.get("summary") or article.get("description") or "").lower()
        if article.get("quote_text"):
            cat = "QUOTE"

    combined = f"{cat} {topic} {title} {summary}".lower()

    if any(k in combined for k in ("health", "medical", "disease", "outbreak", "virus", "infection", "vaccine", "hospital", "who", "cdc", "pandemic", "epidemic", "plague", "cancer", "fever", "mpox", "avian flu", "bird flu", "cholera")):
        return render_health_illustration(width, height)
    if any(k in combined for k in ("quote", "statement", "remarks", "said", "testimony", "speech")):
        return render_quote_illustration(width, height)
    if any(k in combined for k in ("ballot", "ballots", "election", "elections", "voting", "vote", "votes", "polling", "poll", "polls", "electoral", "primary", "caucus", "referendum", "precinct")):
        return render_election_illustration(width, height)
    if any(k in combined for k in ("fire", "wildfire", "emergency", "disaster", "earthquake", "flood", "storm", "hurricane", "typhoon", "cyclone", "evacuation", "explosion", "blast", "tsunami", "volcano")):
        return render_crisis_illustration(width, height)
    if any(k in combined for k in ("business", "economy", "finance", "market", "trade", "stock", "banking", "inflation", "rate", "rates", "dollar", "treasury", "revenue", "gdp", "crypto")):
        return render_finance_illustration(width, height)
    if any(k in combined for k in ("technology", "tech", "science", "space", "artificial intelligence", "ai", "software", "cyber", "quantum", "semiconductor", "chip", "chips", "satellite", "spacewalk", "nasa")):
        return render_tech_illustration(width, height)
    if any(k in combined for k in ("diplomacy", "treaty", "sanctions", "sanction", "summit", "accord", "alliance", "united nations", "geopolitics", "international", "ambassador", "foreign", "icc", "icj")):
        label = "DIPLOMACY & SANCTIONS ILLUSTRATION" if any(s in combined for s in ("sanction", "sanctions", "icc", "icj")) else "GLOBAL AFFAIRS ILLUSTRATION"
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

# ==============================================================================
# HIGH-IMPACT EDITORIAL TEMPLATES (A: Political, B: Business/Tech, C: Breaking/Health)
# ==============================================================================

def draw_template_political(article, post, photos=None):
    """Template A: Political News — High-Impact Editorial Layout.

    Dramatic photo collage or dominant hero photograph using relevant politicians,
    institutions or locations. Oversized white headline typography with selective
    yellow and red emphasis, clear headline hierarchy, and strong bottom information strip.
    """
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (8, 12, 22, 255))
    d = ImageDraw.Draw(canvas)

    # 1. Header (y: 35 to 88)
    draw_brand_slash(d, 55, 42, scale=1.05)
    draw_globe_icon(d, 790, 62, r=12, color=WHITE)
    date_str = get_current_date_str("%d %b %Y").upper()
    d.text((812, 51), date_str, font=font(19, True), fill=WHITE)

    # 2. Photo Area (y: 105 to 680)
    photo_box = (45, 105, 1035, 680)
    photo_list = [photos] if isinstance(photos, dict) else (photos or [])
    real_photos = [p for p in photo_list if p and isinstance(p.get("image"), Image.Image)]

    pw = photo_box[2] - photo_box[0]
    ph = photo_box[3] - photo_box[1]

    if len(real_photos) >= 2:
        # Editorial Photo Collage: Dominant hero on left (62%), secondary institutional on right (38%)
        p1, p2 = real_photos[0], real_photos[1]
        split_x = photo_box[0] + int(pw * 0.62)
        crop_photo(canvas, p1, (photo_box[0], photo_box[1], split_x, photo_box[3]), category="POLITICS", centering=(0.5, 0.25), article=article, draw_label=True, label_position="top_left")
        crop_photo(canvas, p2, (split_x, photo_box[1], photo_box[2], photo_box[3]), category="POLITICS", centering=(0.5, 0.5), article=article, draw_label=True, label_position="top_right")
        # Dramatic slanted red divider line between images
        cd = ImageDraw.Draw(canvas)
        slash_offset = 20
        cd.polygon([
            (split_x - slash_offset, photo_box[1]),
            (split_x - slash_offset + 6, photo_box[1]),
            (split_x + slash_offset + 6, photo_box[3]),
            (split_x + slash_offset, photo_box[3])
        ], fill=(230, 31, 45))
    elif len(real_photos) == 1:
        crop_photo(canvas, real_photos[0], photo_box, category="POLITICS", centering=(0.5, 0.25), article=article, draw_label=True, label_position="top_right")
    else:
        ill = make_illustration(pw, ph, category="POLITICS", article=article)
        canvas.paste(ill.convert("RGBA"), (photo_box[0], photo_box[1]))

    # Dark bottom gradient overlay
    draw_photo_overlay(canvas, (photo_box[0], photo_box[3] - 220, photo_box[2], photo_box[3]), strength=230)

    d = ImageDraw.Draw(canvas)

    # 3. Category badge
    cat_text = category_label(article)
    if cat_text.upper() in {"GLOBAL NEWS", "NEWS"}:
        cat_text = "POLITICS & GOVERNANCE"
    add_pill(d, (55, 695, 410, 742), cat_text.upper(), fill=(195, 20, 35), text_fill=WHITE, max_font=19)

    # Red vertical accent bar on left of headline
    d.rectangle((55, 755, 63, 965), fill=(230, 31, 45))

    # 4. Oversized Headline
    headline = post.get("headline", "").strip().upper()
    draw_two_tone_headline(
        d, headline, (78, 748, 1025, 965),
        accent_mode="bottom_yellow",
        max_size=64, min_size=36, max_lines=4,
        with_shadow=True
    )

    # 5. Summary
    summary = post.get("summary", "").strip() or summary_from_caption(post.get("caption", ""), 45)
    draw_wrapped(
        d, summary, (78, 980, 1025, 1180),
        max_size=26, min_size=20, bold=False,
        fill=(210, 222, 235), max_lines=5, line_multiplier=1.24
    )

    # 6. Bottom Information Strip
    d.rounded_rectangle((45, 1215, 1035, 1305), radius=16, fill=(14, 22, 38), outline=(28, 42, 68), width=1)
    source_domain = str(article.get("domain", "NEWS-SNAP")).strip().upper()
    d.text((70, 1242), f"SOURCE: {source_domain}  •  {date_str}", font=font(19, True), fill=WHITE)
    draw_centered(d, (720, 1215, 1010, 1305), "DETAILS IN CAPTION →", font(20, True), (255, 207, 45))

    return canvas


def draw_template_business_tech(article, post, photos=None):
    """Template B: Business & Technology News — High-Impact Editorial Layout.

    Large relevant photography / executive portrait, bold typography, high contrast,
    dramatic composition and selective red/yellow highlights.
    """
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (6, 10, 18, 255))

    # 1. Photo area: Top 0 to 740
    photo_box = (0, 0, WIDTH, 740)
    photo_list = [photos] if isinstance(photos, dict) else (photos or [])
    real_photos = [p for p in photo_list if p and isinstance(p.get("image"), Image.Image)]

    pw, ph = WIDTH, 740

    if len(real_photos) >= 2:
        p1, p2 = real_photos[0], real_photos[1]
        split_x = int(pw * 0.65)
        crop_photo(canvas, p1, (0, 0, split_x, ph), category="BUSINESS", centering=(0.5, 0.22), article=article, draw_label=False)
        crop_photo(canvas, p2, (split_x, 0, pw, ph), category="TECHNOLOGY", centering=(0.5, 0.5), article=article, draw_label=True, label_position="top_right")
        cd = ImageDraw.Draw(canvas)
        cd.line((split_x, 0, split_x, ph), fill=(56, 189, 248), width=3)
    elif len(real_photos) == 1:
        crop_photo(canvas, real_photos[0], photo_box, category="BUSINESS", centering=(0.5, 0.22), article=article, draw_label=False)
        topic = str(article.get("classification", {}).get("topic", "")).lower()
        title = str(article.get("title", "")).lower()
        if any(k in title or k in topic for k in ("ceo", "executive", "founder", "musk", "altman", "nadella", "cook", "leadership", "people")):
            box_crop = canvas.crop(photo_box).convert("L").convert("RGBA")
            canvas.paste(box_crop, (0, 0))
        lbl = determine_photo_label(real_photos[0], article)
        if lbl:
            draw_photo_label(canvas, photo_box, lbl, position="top_right")
    else:
        ill = make_illustration(pw, ph, category="BUSINESS", article=article)
        canvas.paste(ill.convert("RGBA"), (0, 0))

    # Dramatic bottom vignette gradient overlay fading into carbon black
    draw_photo_overlay(canvas, (0, 420, WIDTH, 740), strength=245)

    d = ImageDraw.Draw(canvas)

    # 2. Header
    draw_brand_slash(d, 55, 45, scale=1.05)
    date_str = get_current_date_str("%d %b %Y").upper()
    d.rectangle((760, 52, 782, 74), outline=WHITE, width=2)
    d.line((760, 60, 782, 60), fill=WHITE, width=2)
    d.text((794, 50), date_str, font=font(19, True), fill=WHITE)

    # 3. Category badge at (55, 680)
    badge_label = "BUSINESS & TECH"
    topic = str(article.get("classification", {}).get("topic", "")).upper()
    if topic in {"TECHNOLOGY", "TECH", "FINANCE", "BUSINESS", "ECONOMY", "MARKETS"}:
        badge_label = topic
    d.rounded_rectangle((55, 680, 55 + 240, 726), radius=14, fill=(10, 24, 45), outline=(56, 189, 248), width=2)
    draw_centered(d, (55, 680, 55 + 240, 726), badge_label, font(19, True), WHITE)

    # 4. Headline (y: 740 to 950)
    headline = post.get("headline", "").strip().upper()
    draw_two_tone_headline(
        d, headline, (55, 740, 1025, 950),
        accent_mode="bottom_yellow",
        max_size=66, min_size=36, max_lines=4,
        with_shadow=True
    )

    # 5. Summary (y: 960 to 1090)
    summary = post.get("summary", "").strip() or summary_from_caption(post.get("caption", ""), 36)
    draw_wrapped(
        d, summary, (55, 965, 1025, 1095),
        max_size=25, min_size=19, bold=False,
        fill=(245, 248, 255), max_lines=4, line_multiplier=1.22
    )

    # 6. Dynamic Topic Pills (y: 1110 to 1160)
    pills = extract_matching_category_tags(article)
    if not pills:
        pills = [("Markets", (28, 100, 242)), ("Technology", (118, 56, 198)), ("Business", (24, 138, 78))]
    px = 55
    for label, col in pills[:3]:
        bbox = d.textbbox((0, 0), label, font=font(18, True))
        pw_pill = max(120, bbox[2] - bbox[0] + 32)
        d.rounded_rectangle((px, 1112, px + pw_pill, 1160), radius=15, fill=col)
        draw_centered(d, (px, 1112, px + pw_pill, 1160), label, font(18, True), WHITE)
        px += pw_pill + 16

    # 7. Bottom Information Strip (y: 1245 to 1305)
    draw_standard_footer(d, category="TECH & MARKETS", cta="DETAILS IN CAPTION →", y=1255, dark=True)

    return canvas


def draw_template_breaking_health(article, post, photos=None):
    """Template C: Breaking News & Health News — High-Impact Urgent Editorial Layout.

    Prominent BREAKING NEWS or BREAKING HEALTH label (only when justified), high-impact
    photography or verified collage, large headline, and verified facts information panel.
    Avoids frightening imagery for disease outbreaks.
    """
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (10, 14, 24, 255))

    title = str(article.get("title", "")).lower()
    topic = str(article.get("classification", {}).get("topic", "")).lower()
    is_health = any(k in title or k in topic for k in (
        "health", "disease", "outbreak", "virus", "infection", "vaccine",
        "medical", "hospital", "who", "cdc", "pandemic", "epidemic", "plague",
        "cancer", "fever", "mpox", "avian flu", "bird flu"
    ))

    d = ImageDraw.Draw(canvas)

    # 1. Header
    draw_brand_slash(d, 55, 42, scale=1.05)
    d.rounded_rectangle((240, 44, 370, 88), radius=14, fill=(230, 31, 45))
    d.ellipse((256, 60, 268, 72), fill=WHITE)
    d.text((278, 52), "LIVE", font=font(20, True), fill=WHITE)

    date_str = get_current_date_str("%d %b %Y").upper()
    d.text((820, 52), date_str, font=font(20, True), fill=WHITE)

    # 2. Urgent Ribbon Banner (y: 105 to 175)
    if is_health:
        d.rounded_rectangle((55, 105, 1025, 175), radius=10, fill=(195, 20, 35))
        d.rectangle((85, 122, 105, 158), fill=WHITE)
        d.rectangle((76, 131, 114, 149), fill=WHITE)
        d.text((130, 122), "BREAKING HEALTH & SCIENCE", font=font(34, True), fill=WHITE)
        for sx in (920, 955):
            d.polygon([(sx, 115), (sx + 16, 115), (sx - 4, 165), (sx - 20, 165)], fill=WHITE)
    else:
        d.rounded_rectangle((55, 105, 1025, 175), radius=10, fill=(230, 31, 45))
        d.text((85, 122), "BREAKING NEWS", font=font(36, True), fill=WHITE)
        for sx in (865, 910, 955):
            d.polygon([(sx, 115), (sx + 20, 115), (sx - 8, 165), (sx - 28, 165)], fill=WHITE)

    # 3. Photo Area (y: 190 to 680)
    photo_box = (55, 190, 1025, 680)
    photo_list = [photos] if isinstance(photos, dict) else (photos or [])
    real_photos = [p for p in photo_list if p and isinstance(p.get("image"), Image.Image)]

    pw = photo_box[2] - photo_box[0]
    ph = photo_box[3] - photo_box[1]

    category_name = "HEALTH" if is_health else emergency_event_label(title)

    if len(real_photos) >= 2:
        p1, p2 = real_photos[0], real_photos[1]
        split_x = photo_box[0] + int(pw * 0.60)
        crop_photo(canvas, p1, (photo_box[0], photo_box[1], split_x, photo_box[3]), category=category_name, article=article, draw_label=True, label_position="top_left")
        crop_photo(canvas, p2, (split_x, photo_box[1], photo_box[2], photo_box[3]), category=category_name, article=article, draw_label=True, label_position="top_right")
        cd = ImageDraw.Draw(canvas)
        cd.line((split_x, photo_box[1], split_x, photo_box[3]), fill=(230, 31, 45) if not is_health else (195, 20, 35), width=3)
    elif len(real_photos) == 1:
        crop_photo(canvas, real_photos[0], photo_box, category=category_name, article=article, draw_label=True, label_position="top_right")
    else:
        ill = make_illustration(pw, ph, category=category_name, article=article)
        canvas.paste(ill.convert("RGBA"), (photo_box[0], photo_box[1]))

    # Dark bottom gradient overlay
    draw_photo_overlay(canvas, (photo_box[0], photo_box[3] - 200, photo_box[2], photo_box[3]), strength=220)

    d = ImageDraw.Draw(canvas)

    # 4. White vertical accent line on left of headline
    d.rectangle((55, 705, 62, 925), fill=WHITE)

    # 5. Urgent Headline (y: 695 to 925)
    headline = post.get("headline", "").strip().upper()
    draw_two_tone_headline(
        d, headline, (76, 695, 1025, 925),
        accent_mode="bottom_yellow",
        max_size=64, min_size=36, max_lines=4,
        with_shadow=True
    )

    # 6. Verified Developments Information Panel (y: 940 to 1195)
    d.rounded_rectangle((55, 940, 1025, 1195), radius=16, fill=(18, 28, 48), outline=(38, 56, 88), width=1)
    d.text((80, 960), "VERIFIED DEVELOPMENTS:", font=font(18, True), fill=(255, 207, 45))
    summary = post.get("summary", "").strip() or summary_from_caption(post.get("caption", ""), 45)
    draw_wrapped(
        d, summary, (80, 995, 1000, 1175),
        max_size=25, min_size=19, bold=False,
        fill=(240, 246, 255), max_lines=5, line_multiplier=1.24
    )

    # 7. Bottom Strip (y: 1220 to 1310)
    source_domain = str(article.get("domain", "NEWS-SNAP")).strip().upper()
    d.rounded_rectangle((55, 1220, 1025, 1310), radius=16, fill=(12, 18, 30), outline=(24, 36, 56), width=1)
    draw_globe_icon(d, 82, 1265, r=12, color=WHITE)
    d.text((106, 1252), f"SOURCE: {source_domain}  •  {date_str}", font=font(19, True), fill=WHITE)
    draw_centered(d, (720, 1220, 1005, 1310), "DETAILS IN CAPTION →", font(20, True), (255, 207, 45))

    return canvas


def draw_template_neutral_editorial(article, post, photos=None):
    """Neutral Editorial Fallback — Clean, Balanced Editorial Layout."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (8, 14, 26, 255))

    d = ImageDraw.Draw(canvas)
    draw_brand_compass(d, 60, 48, dark=True, scale=1.0)

    # Globe icon + Date
    draw_globe_icon(d, 790, 68, r=12, color=WHITE)
    date_str = get_current_date_str("%d %b %Y").upper()
    d.text((812, 56), date_str, font=font(19, True), fill=WHITE)

    # Photo box
    photo_box = (55, 115, 1025, 685)
    photo_list = [photos] if isinstance(photos, dict) else (photos or [])
    real_photos = [p for p in photo_list if p and isinstance(p.get("image"), Image.Image)]

    pw = photo_box[2] - photo_box[0]
    ph = photo_box[3] - photo_box[1]
    if real_photos:
        crop_photo(canvas, real_photos[0], photo_box, category="GLOBAL NEWS", article=article, draw_label=True, label_position="top_right")
    else:
        ill = make_illustration(pw, ph, category="GLOBAL NEWS", article=article)
        canvas.paste(ill.convert("RGBA"), (photo_box[0], photo_box[1]))

    draw_photo_overlay(canvas, (photo_box[0], photo_box[3] - 200, photo_box[2], photo_box[3]), strength=210)

    d = ImageDraw.Draw(canvas)
    # Category pill
    add_pill(d, (55, 705, 330, 755), "EDITORIAL REPORT", fill=(24, 48, 80), text_fill=WHITE, max_font=19)

    # Headline
    headline = post.get("headline", "").strip().upper()
    draw_two_tone_headline(
        d, headline, (55, 765, 1025, 960),
        accent_mode="top_yellow",
        max_size=60, min_size=36, max_lines=4,
        with_shadow=True
    )

    # Summary
    summary = post.get("summary", "").strip() or summary_from_caption(post.get("caption", ""), 45)
    draw_wrapped(
        d, summary, (55, 980, 1025, 1180),
        max_size=25, min_size=19, bold=False,
        fill=(210, 222, 235), max_lines=6, line_multiplier=1.24
    )

    # Footer
    draw_standard_footer(d, category="WORLD NEWS", cta="DETAILS IN CAPTION →", y=1255, dark=True)
    return canvas


def draw_template_01(article, post, photo):
    """Format 01: LIVE / DEVELOPING NEWS (Emergencies & Disasters)"""
    return draw_template_breaking_health(article, post, [photo] if photo else None)


def draw_template_02(article, post, photo):
    """Format 02: BUSINESS & ECONOMY (Markets & Money)"""
    return draw_template_business_tech(article, post, [photo] if photo else None)


def draw_template_03(article, post, photo):
    """Format 03: PEOPLE & CORPORATE STORIES"""
    return draw_template_business_tech(article, post, [photo] if photo else None)


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
        crop_photo(canvas, photo, (85, y + 8, 325, y + 207), category=category_label(story), article=story, label_position="top_left")
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
    """Format 05: SINGLE-STORY NEWS REPORT (Political & General)"""
    return draw_template_political(article, post, [photo] if photo else None)


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


def strip_image_credits(caption: str) -> str:
    """Remove any previously appended image credit block from caption."""
    if not caption:
        return ""
    parts = re.split(
        r"\n\s*(?:(?:Story|Photo)\s+\d+\s+)?(?:Image credit:|(?:Illustrative )?image credit:|Image licence:|Image source:)",
        str(caption), maxsplit=1, flags=re.I
    )
    return parts[0].strip()


def annotate_image_credit(post, photo_info, caption_path="post.json", story_index=None, photo_index=None):
    if not photo_info:
        return
    if isinstance(photo_info, list):
        valid_photos = [p for p in photo_info if p and isinstance(p.get("image"), Image.Image) and p.get("page_url")]
        if not valid_photos:
            return
        for idx, p in enumerate(valid_photos, start=1):
            p_idx = idx if len(valid_photos) > 1 else None
            annotate_image_credit(post, p, caption_path=caption_path, photo_index=p_idx)
        return

    if "image" in photo_info and (photo_info["image"] is None or not isinstance(photo_info["image"], Image.Image)):
        return
    if not photo_info.get("page_url") or not photo_info.get("license"):
        return
    caption = str(post.get("caption", "")).strip()
    if photo_info["page_url"] in caption:
        return

    if story_index is not None:
        prefix = f"Story {story_index} "
    elif photo_index is not None:
        prefix = f"Photo {photo_index} "
    else:
        prefix = ""

    artist_name = photo_info.get("artist") or photo_info.get("author") or "Unknown"
    title_str = photo_info.get("title") or "Photo"
    license_str = photo_info.get("license") or "CC"
    credit_parts = [
        f"{prefix}Image credit: {title_str} by {artist_name}.",
        f"Licence: {license_str}.",
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


def select_editorial_template(article: dict, roundup_exists: bool = False) -> tuple[str, str]:
    """Deterministically select the editorial layout template based on article category and content.

    Templates:
    - 'political': Template A — Political News
    - 'business_tech': Template B — Business & Technology News
    - 'breaking_health': Template C — Breaking News & Health News
    - 'editorial': Neutral Editorial Fallback

    Special preservation formats:
    - '04': Daily Headlines Roundup
    - '06': Verified Statement / Quote
    """
    override = str(article.get("template_override", "")).strip().lower()
    if override in {"4", "04", "roundup", "daily_headlines"}:
        if not roundup_exists:
            raise ValueError("Format 04 requires roundup.json and roundup_post.json")
        return "04", "Selected via explicit template_override: Format 04 (Daily Headlines Roundup)"
    if override in {"6", "06", "quote", "statement"}:
        if not (article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker")):
            raise ValueError("Format 06 requires verified quote_text and speaker in selected_article.json")
        return "06", "Selected via explicit template_override: Format 06 (Verified Statement / Quote)"
    if override in {"a", "political", "politics", "5", "05"}:
        return "political", "Selected via explicit template_override: Template A (Political News)"
    if override in {"b", "business", "tech", "technology", "business_tech", "2", "02", "3", "03"}:
        return "business_tech", "Selected via explicit template_override: Template B (Business & Technology)"
    if override in {"c", "breaking", "health", "emergency", "breaking_health", "1", "01"}:
        return "breaking_health", "Selected via explicit template_override: Template C (Breaking & Health News)"
    if override in {"editorial", "neutral"}:
        return "editorial", "Selected via explicit template_override: Neutral Editorial Fallback"

    # Rule 1: Verified statement with quote and speaker -> Format 06
    if article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker"):
        return "06", "Article contains source-verified quotation and speaker; qualifies for Format 06 (Verified Statement / Quote)"

    title = str(article.get("title", "")).lower()
    topic = str(article.get("classification", {}).get("topic", "")).lower()
    summary = str(article.get("summary") or article.get("description", "")).lower()
    combined = f"{title} {topic} {summary}"

    def _has_keyword(text: str, kw: str) -> bool:
        if " " in kw:
            return kw in text
        return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))

    # Rule 2: Breaking News & Health News (Template C)
    health_keywords = (
        "health", "outbreak", "virus", "disease", "infection", "epidemic", "pandemic",
        "plague", "who", "cdc", "vaccine", "medical", "hospital", "cancer", "mpox",
        "avian flu", "bird flu", "cholera", "fever", "respiratory", "pathogen"
    )
    emergency_keywords = (
        "wildfire", "wildfires", "forest fire", "flood", "floods", "flooding",
        "earthquake", "quake", "aftershock", "hurricane", "cyclone", "typhoon",
        "tsunami", "evacuation", "evacuations", "landslide", "volcano", "volcanic",
        "explosion", "disaster", "rescue operation", "mass casualty", "severe storm"
    )
    if any(_has_keyword(combined, k) for k in health_keywords) or any(_has_keyword(combined, k) for k in emergency_keywords):
        sub_type = "Health Alert" if any(_has_keyword(combined, k) for k in health_keywords) else "Urgent Breaking/Emergency"
        return "breaking_health", f"{sub_type} indicators detected; matched Template C (Breaking News & Health News)"

    # Rule 3: Business & Technology News (Template B)
    business_tech_keywords = (
        "business", "economy", "finance", "market", "markets", "trade", "inflation",
        "interest rate", "gdp", "revenue", "earnings", "profit", "stocks", "shares",
        "stock market", "nasdaq", "dow", "s&p", "central bank", "federal reserve",
        "budget", "ceo", "chief executive", "founder", "semiconductor", "chip",
        "chips", "ai", "artificial intelligence", "tech", "technology", "software",
        "spacex", "tesla", "apple", "google", "microsoft", "nvidia", "amazon",
        "meta", "crypto", "bitcoin", "startup", "ipo", "electric vehicle"
    )
    if any(_has_keyword(combined, k) for k in business_tech_keywords) or any(_has_keyword(topic, t) for t in ("business", "economy", "finance", "market", "technology", "tech")):
        return "business_tech", "Business or technology indicators detected; matched Template B (Business & Technology News)"

    # Rule 4: Political News (Template A)
    political_keywords = (
        "politics", "political", "government", "parliament", "congress", "senate",
        "election", "vote", "poll", "minister", "prime minister", "president",
        "bjp", "rahul gandhi", "modi", "biden", "trump", "starmer", "macron",
        "scholz", "cabinet", "white house", "kremlin", "lok sabha", "rajya sabha",
        "supreme court", "legislation", "bill passed", "ambassador", "diplomacy",
        "diplomatic", "sanctions", "treaty", "nato", "united nations"
    )
    if any(_has_keyword(combined, k) for k in political_keywords) or any(_has_keyword(topic, t) for t in ("politics", "government", "diplomacy", "election")):
        return "political", "Political or governmental indicators detected; matched Template A (Political News)"

    # Rule 5: Fallback to neutral editorial
    return "editorial", "Uncertain or general category; matched neutral editorial fallback"


def render_approved_format(template_id, article, post, photos=None):
    """Render the exact approved format (01-06) or editorial template (political, business_tech, breaking_health)."""
    raw_tid = str(template_id).strip()
    tid = raw_tid.lower()

    # Map friendly aliases
    alias_map = {
        "a": "political",
        "template_a": "political",
        "b": "business_tech",
        "template_b": "business_tech",
        "c": "breaking_health",
        "template_c": "breaking_health",
        "neutral": "editorial",
    }
    tid = alias_map.get(tid, tid)

    allowed_ids = list(FORMAT_REGISTRY.keys()) + ["political", "business_tech", "breaking_health", "editorial", "a", "b", "c"]
    if tid not in allowed_ids and raw_tid.zfill(2) not in FORMAT_REGISTRY:
        raise ValueError(f"Unrecognized format {template_id}. Must be one of {allowed_ids}")

    if tid == "04":
        stories, roundup_post = load_roundup()
        resolved_photos = photos if photos is not None else [query_commons_image(s) for s in stories]
        image = draw_template_04(article, roundup_post, stories, resolved_photos)
        return image, roundup_post, resolved_photos

    if tid == "06":
        if article.get("quote_verified") is not True or not article.get("quote_text") or not article.get("speaker"):
            raise ValueError(
                "Format 06 REFUSAL: Quotation cannot be verified from original source (quote_verified is not True). "
                "Never present unverified or rewritten quotations inside quotation marks. "
                "Skip Format 06 and use an appropriate non-quote format instead."
            )
        photo = photos if photos is not None else query_commons_image(article.get("speaker", ""), require_all_terms=True)
        if isinstance(photo, list):
            photo = photo[0] if photo else None
        image = draw_template_06(article, post, photo)
        return image, post, [photo]

    # For other templates, query up to 2 genuine relevant photos for collage capability if not provided
    if photos is None:
        resolved_photos = query_commons_images(article, max_images=2)
    elif isinstance(photos, dict):
        resolved_photos = [photos]
    else:
        resolved_photos = list(photos)
    primary_photo = resolved_photos[0] if resolved_photos else None

    if tid in {"01", "breaking_health"}:
        image = draw_template_breaking_health(article, post, resolved_photos)
    elif tid in {"02", "03", "business_tech"}:
        image = draw_template_business_tech(article, post, resolved_photos)
    elif tid in {"05", "political"}:
        image = draw_template_political(article, post, resolved_photos)
    elif tid == "editorial":
        image = draw_template_neutral_editorial(article, post, resolved_photos)
    else:
        raise ValueError(f"Unknown NEWS SNAP template: {template_id}")

    return image, post, resolved_photos or [primary_photo]


def main():
    if OUTPUT.is_file():
        try:
            OUTPUT.unlink()
        except OSError:
            pass

    post_path = Path("post.json")
    article_path = Path("selected_article.json")
    if not post_path.is_file() or not article_path.is_file():
        print("[INFO] post.json or selected_article.json missing. Skipping image generation.")
        return

    post = json.loads(post_path.read_text(encoding="utf-8"))
    article = json.loads(article_path.read_text(encoding="utf-8"))

    try:
        # Determine template using editorial layout selection
        roundup_exists = Path("roundup.json").is_file() and Path("roundup_post.json").is_file()
        forced = os.environ.get("NEWS_SNAP_FORCE_TEMPLATE")
        if forced:
            template_id = forced.strip()
            selection_reason = f"Forced via environment variable: {template_id}"
        else:
            template_id, selection_reason = select_editorial_template(article, roundup_exists)

        if template_id == "06" and not (article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker")):
            print("[WARN] Format 06 skipped: quote is not source-verified (quote_verified is not True). Using appropriate non-quote format instead.")
            clean_article = dict(article)
            clean_article.pop("quote_text", None)
            clean_article.pop("quote_verified", None)
            template_id, selection_reason = select_editorial_template(clean_article, roundup_exists)

        format_name = FORMAT_REGISTRY.get(template_id, {}).get("name", template_id.upper())
        print(f"Template Selected: {template_id} — {format_name}")
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
            real_photos = [info for info in photo_infos if info and isinstance(info.get("image"), Image.Image)]
            if real_photos:
                for idx, info in enumerate(photo_infos, start=1):
                    if info and isinstance(info.get("image"), Image.Image):
                        annotate_image_credit(rendered_post, info, caption_path="post.json", story_index=idx)
            else:
                rendered_post["caption"] = strip_image_credits(rendered_post.get("caption", ""))
            Path("roundup_post.json").write_text(json.dumps(rendered_post, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            valid_photos = [p for p in photo_infos if p and isinstance(p.get("image"), Image.Image)]
            if valid_photos:
                annotate_image_credit(rendered_post, valid_photos, caption_path="post.json")
            else:
                rendered_post["caption"] = strip_image_credits(rendered_post.get("caption", ""))
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
        print(f"Format Name: {format_name}")
        print(f"Dimensions: {WIDTH}x{HEIGHT}")
        print(f"Source: {source}")
    except ValueError as val_err:
        print(f"[IMAGE GENERATION REJECTION] {val_err}", file=sys.stderr)
        if article and isinstance(article, dict):
            try:
                from post_generator import record_rejected_story
                record_rejected_story(article, reason=str(val_err))
                print(f"[REJECTION] Recorded unrenderable story in history.json: {val_err}")
            except Exception as e:
                print(f"[WARN] Failed to record rejected story: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

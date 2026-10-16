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


def words_for_query(text):
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return [w for w in tokens if len(w) >= 4 and w not in STOP_WORDS][:8]


MAP_DIAGRAM_DISQUALIFIERS = {
    "map", "maps", "mapping", "satellite", "aviris", "modis", "copernicus",
    "heat signature", "infrared", "orbit", "sensor", "diagram", "chart",
    "graph", "screenshot", "icon", "logo", "symbol", "infographic", "drawing"
}


def license_allowed(short_name):
    low = re.sub(r"\s+", " ", str(short_name or "").strip().lower())
    if not low:
        return False
    # Strictly forbid non-commercial and no-derivatives licences
    if any(m in low for m in ("noncommercial", "non-commercial", "by-nc", "no derivatives", "by-nd")):
        return False
    if "cc0" in low or "public domain" in low or "godl" in low or "attribution" in low:
        return True
    return "cc by" in low or "cc-by" in low


def query_commons_image(query, require_all_terms=False):
    if os.environ.get("NEWS_SNAP_OFFLINE_PREVIEW") == "1":
        return None
    query_terms = words_for_query(query)[:5]
    if not query_terms:
        print("Photo sourcing: no useful English keywords; using labelled illustration.")
        return None
    if require_all_terms and len(query_terms) < 2:
        print("Photo sourcing: speaker name is too short to identify a portrait safely.")
        return None

    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": "filetype:bitmap " + " ".join(query_terms),
        "gsrnamespace": 6,
        "gsrlimit": 15,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1200,
        "format": "json",
    }
    request_url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(request_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.load(response)
    except Exception as exc:
        print(f"Photo sourcing: Commons search unavailable ({type(exc).__name__}); using labelled illustration.")
        return None

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

        title = clean_html(page.get("title", "").replace("File:", ""))
        description = clean_html(metadata.get("ImageDescription", {}).get("value", ""))
        if not is_latin_script(title):
            continue
        if any(bad in title.lower() for bad in MAP_DIAGRAM_DISQUALIFIERS):
            continue
        candidate_text = (title + " " + description).lower()
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

    if not best:
        print("Photo sourcing: no sufficiently relevant, approved-license result; using labelled illustration.")
        return None

    try:
        image_req = urllib.request.Request(best["thumb_url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(image_req, timeout=15) as response:
            raw = response.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            return None
        with Image.open(BytesIO(raw)) as im:
            best["image"] = im.convert("RGB")
        safe_license = unicodedata.normalize("NFKD", best["license"]).encode("ascii", "ignore").decode("ascii")
        print(f"Photo sourcing: accepted Commons image (licence={safe_license}, match={best['score']:.2f}).")
        return best
    except Exception as exc:
        print(f"Photo sourcing: download failed ({type(exc).__name__}); using labelled illustration.")
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

    # Extract complete sentences to prevent cutting off mid-sentence
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

    # Guarantee sentence ends cleanly with complete punctuation (never an ellipsis)
    text = text.rstrip(".… ") + "."
    text = text or "Read the original report for full details and context."
    return validate_english_text(text, "visible summary")


def add_pill(draw, box, text, fill=RED, text_fill=WHITE, max_font=28):
    draw.rounded_rectangle(box, radius=15, fill=fill)
    draw_centered(draw, box, text, font(max_font, True), text_fill)


def crop_photo(canvas, photo_info, box, category="GLOBAL NEWS", centering=(0.5, 0.5)):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if photo_info and isinstance(photo_info.get("image"), Image.Image):
        photo = ImageOps.fit(photo_info["image"], (w, h), method=Image.Resampling.LANCZOS, centering=centering)
        canvas.paste(photo.convert("RGBA"), (x1, y1))
        return True
    fallback = make_illustration(w, h, category)
    canvas.paste(fallback, (x1, y1))
    return False


def make_illustration(width, height, category):
    """Generate a deliberate, polished editorial graphic when no photo is available.

    Never outputs confusing black shapes or broken-looking placeholders.
    """
    cat = str(category or "").upper()
    if any(k in cat for k in ("FIRE", "EMERGENCY", "DISASTER", "EARTHQUAKE", "FLOOD", "STORM")):
        bg_top, bg_bot = (32, 12, 12), (14, 18, 28)
        accent_color = (230, 31, 45)
    elif any(k in cat for k in ("BUSINESS", "ECONOMY", "FINANCE", "MARKET")):
        bg_top, bg_bot = (12, 28, 54), (6, 16, 32)
        accent_color = (255, 207, 45)
    elif any(k in cat for k in ("PEOPLE", "LEADERSHIP", "CORPORATE")):
        bg_top, bg_bot = (20, 24, 34), (10, 12, 18)
        accent_color = (180, 200, 225)
    elif any(k in cat for k in ("QUOTE", "STATEMENT")):
        bg_top, bg_bot = (10, 48, 36), (5, 26, 20)
        accent_color = (30, 126, 52)
    else:
        bg_top, bg_bot = (14, 26, 46), (8, 14, 26)
        accent_color = (230, 31, 45)

    im = Image.new("RGB", (width, height), bg_top)
    d = ImageDraw.Draw(im)

    # Smooth vertical gradient
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(bg_top[0] * (1 - t) + bg_bot[0] * t)
        g = int(bg_top[1] * (1 - t) + bg_bot[1] * t)
        b = int(bg_top[2] * (1 - t) + bg_bot[2] * t)
        d.line((0, y, width, y), fill=(r, g, b))

    # Subtle modern geometric grid
    grid_step = max(30, width // 16)
    for gx in range(0, width, grid_step):
        d.line((gx, 0, gx, height), fill=(255, 255, 255, 12), width=1)
    for gy in range(0, height, grid_step):
        d.line((0, gy, width, gy), fill=(255, 255, 255, 12), width=1)

    # Clean atmospheric center glow
    cx, cy = width // 2, height // 2
    glow_r = min(width, height) // 3
    d.ellipse((cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r), outline=accent_color, width=2)
    d.ellipse((cx - glow_r // 2, cy - glow_r // 2, cx + glow_r // 2, cy + glow_r // 2), outline=(255, 255, 255), width=1)

    # Polished editorial badge
    badge_label = f"NEWS SNAP  •  {cat if len(cat) <= 22 else 'EDITORIAL'}"
    draw_centered(d, (0, cy - 14, width, cy + 14), badge_label, font(max(15, min(22, width // 35)), True), (240, 245, 255))
    return im


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
    crop_photo(canvas, photo, (0, 0, WIDTH, 840), category=emergency_event_label(str(article.get("title", ""))))
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
    crop_photo(canvas, photo, (65, 125, 1015, 615), category="BUSINESS")
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
    crop_photo(canvas, photo, (0, 0, WIDTH, 890), category="PEOPLE", centering=(0.5, 0.22))
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
        crop_photo(canvas, photo, (85, y + 8, 325, y + 207), category=category_label(story))
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
    crop_photo(canvas, photo, (75, 230, 1005, 650), category=category_label(article))
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
    quote = validate_english_text(article.get("quote_text"), "verified quotation", 5, 45)
    speaker = validate_english_text(article.get("speaker"), "speaker name", 1, 8)

    # Textured deep emerald canvas
    canvas = gradient(top=(7, 52, 39), bottom=(4, 32, 25))

    # Place verified speaker portrait on right side FIRST (so torn paper overlaps it cleanly)
    crop_photo(canvas, photo, (500, 190, 1030, 1190), category="PEOPLE", centering=(0.5, 0.22))

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


def annotate_image_credit(post, photo_info, caption_path="post.json"):
    if not photo_info:
        return
    caption = str(post.get("caption", "")).strip()
    if photo_info["page_url"] in caption:
        return

    credit_parts = [
        f"Image credit: {photo_info['title']} by {photo_info['artist']}.",
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
        photos = [query_commons_image(s.get("image_search_query") or s["title"]) for s in stories]
        image = draw_template_04(article, roundup_post, stories, photos)
        return image, roundup_post, photos

    if template_id == "06":
        photo = query_commons_image(article.get("speaker", ""), require_all_terms=True)
    else:
        photo_query = article.get("image_search_query") or article.get("title", "")
        photo = query_commons_image(photo_query)

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
        raise FileNotFoundError("post.json and selected_article.json are both required")

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
    caption_path = "roundup_post.json" if template_id == "04" else "post.json"
    for info in photo_infos:
        if info:
            annotate_image_credit(rendered_post, info, caption_path=caption_path)

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

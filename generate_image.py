"""NEWS SNAP multi-template generator.

Inputs: post.json and selected_article.json.
Optional format 04 inputs: roundup.json and roundup_post.json.
Optional quote fields for format 06: quote_text, speaker, quote_verified=True.

Uses original Pillow layouts and, when a suitable freely reusable image is found,
a Wikimedia Commons thumbnail with a compatible licence and caption attribution.
If no suitable image can be found, the card uses clearly-labelled original vector art.
Requires Pillow and langdetect in the production workflow.
"""

import html
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

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
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
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
    path = FONT_BOLD if bold else FONT_REGULAR
    if Path(path).exists():
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


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
    if letters < 8:
        return False
    if not LANGDETECT_AVAILABLE:
        # Local preview mode may test layout only; production must have langdetect.
        return os.environ.get("NEWS_SNAP_TEST_MODE") == "1"
    try:
        predictions = detect_langs(text)
        return bool(
            predictions
            and predictions[0].lang == "en"
            and predictions[0].prob >= minimum_confidence
        )
    except LangDetectException:
        return False


def validate_english_text(text, label, min_words=None, max_words=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Missing required text: {label}")
    text = text.strip()
    if not is_latin_script(text):
        raise ValueError(f"Rejected {label}: non-Latin script detected")
    if not is_likely_english(text):
        raise ValueError(f"Rejected {label}: not confidently English")
    wc = len(text.split())
    if min_words is not None and wc < min_words:
        raise ValueError(f"Rejected {label}: too few words")
    if max_words is not None and wc > max_words:
        raise ValueError(f"Rejected {label}: too many words")
    return text


def wrap(draw, text, ft, max_width):
    lines, current = [], ""
    for word in text.split():
        bbox = draw.textbbox((0, 0), word, font=ft)
        if bbox[2] - bbox[0] > max_width:
            raise ValueError("A single word is too wide for the fixed layout")
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


def draw_wrapped(draw, text, box, max_size=70, min_size=28, bold=True,
                 fill=WHITE, max_lines=5, line_multiplier=1.14, align="left"):
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
                draw.text((x, y), line, font=ft, fill=fill,
                          stroke_width=1 if bold else 0,
                          stroke_fill=(0, 0, 0) if bold else None)
                y += line_h
            return ft, lines
    raise ValueError("Text cannot fit the approved template without clipping")


def draw_centered(draw, box, text, ft, fill):
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=ft)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if text_w > x2 - x1 - 20:
        raise ValueError(f"Label does not fit its layout: {text}")
    x = x1 + ((x2 - x1) - text_w) // 2
    y = y1 + ((y2 - y1) - text_h) // 2 - bbox[1]
    draw.text((x, y), text, font=ft, fill=fill)


def brand(draw, x=42, y=32, compact=False):
    if compact:
        draw.rounded_rectangle((x, y, x + 238, y + 70), radius=14,
                               fill=(3, 9, 19), outline=(235, 241, 249), width=2)
        draw.text((x + 14, y + 4), "NEWS", font=font(29, True), fill=WHITE)
        draw.text((x + 14, y + 32), "SNAP", font=font(29, True), fill=RED)
    else:
        draw.rounded_rectangle((x, y, x + 260, y + 108), radius=18,
                               fill=(3, 9, 19), outline=(235, 241, 249), width=3)
        draw.text((x + 18, y + 5), "NEWS", font=font(47, True), fill=WHITE)
        draw.text((x + 18, y + 50), "SNAP", font=font(47, True), fill=RED)


def gradient(height=HEIGHT, top=(5, 12, 25), bottom=(12, 29, 51)):
    """Fast vertical gradient using horizontal lines rather than per-pixel loops."""
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
    # Normalize accented names (for example, António) before tokenizing.
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return [w for w in tokens if len(w) >= 4 and w not in STOP_WORDS][:8]


def license_allowed(short_name):
    """Allow only straightforward reuse licenses suitable for an image composite.

    CC BY-SA is deliberately excluded to avoid ShareAlike obligations on a
    modified composite. CC BY-NC and CC BY-ND are also excluded.
    """
    low = re.sub(r"\s+", " ", str(short_name or "").strip().lower())
    if not low:
        return False
    if any(marker in low for marker in ("noncommercial", "non-commercial", "by-nc", "no derivatives", "by-nd")):
        return False
    if "cc by-sa" in low or "cc by sa" in low:
        return False
    if "cc0" in low or "public domain" in low:
        return True
    return "cc by " in low


def query_commons_image(query, require_all_terms=False):
    """Download a topic-matching Commons image only when metadata passes checks.

    Accepted licenses: Public Domain, CC0 and CC BY. NC, ND and ShareAlike
    licenses are excluded. At least two meaningful query terms must match title
    or description; quote portraits require all speaker-name terms to match.
    These are automated screening checks, not a legal guarantee or proof that a
    photo depicts the exact event. Every reused photo is labelled as a reference
    image and receives credit, license, source link and edit disclosure in caption.
    """
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
        # The title will be included in attribution, so avoid non-Latin titles.
        if not is_latin_script(title):
            continue
        candidate_text = (title + " " + description).lower()
        normalized_candidate = unicodedata.normalize("NFKD", candidate_text)
        normalized_candidate = normalized_candidate.encode("ascii", "ignore").decode("ascii")
        candidate_tokens = set(re.findall(r"[a-z0-9]+", normalized_candidate))
        matches = query_set.intersection(candidate_tokens)
        score = len(matches) / max(1, len(query_set))
        required_matches = len(query_set) if require_all_terms else min(2, len(query_set))
        if len(matches) < required_matches or score < 0.30 or score <= best_score:
            continue

        artist = clean_html(metadata.get("Artist", {}).get("value", ""))
        # For CC BY, require creator attribution and a direct license URL.
        if "cc by" in license_name.lower() and (not artist or not is_latin_script(artist)):
            continue
        license_url = clean_html(metadata.get("LicenseUrl", {}).get("value", ""))
        if "cc by" in license_name.lower() and not license_url:
            continue
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
            print("Photo sourcing: candidate image exceeded the download limit; using illustration.")
            return None
        with Image.open(BytesIO(raw)) as im:
            im.verify()
        with Image.open(BytesIO(raw)) as im:
            best["image"] = im.convert("RGB")
        print(f"Photo sourcing: accepted Commons image (licence={best['license']}, match={best['score']:.2f}).")
        return best
    except Exception as exc:
        print(f"Photo sourcing: image download/validation failed ({type(exc).__name__}); using labelled illustration.")
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


def template_for(article, roundup_exists=False):
    override = str(article.get("template_override", "")).strip().lower()
    if override in {"1", "01", "developing", "emergency"}:
        return "01"
    if override in {"2", "02", "business", "economy"}:
        return "02"
    if override in {"3", "03", "people", "corporate"}:
        return "03"
    if override in {"4", "04", "roundup", "daily_headlines"}:
        if not roundup_exists:
            raise ValueError("Format 04 requires roundup.json and roundup_post.json")
        return "04"
    if override in {"5", "05", "report", "single_story"}:
        return "05"
    if override in {"6", "06", "quote", "statement"}:
        if not (article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker")):
            raise ValueError("Format 06 requires a verified quote_text and speaker in selected_article.json")
        return "06"

    title = str(article.get("title", "")).lower()
    topic = str(article.get("classification", {}).get("topic", "")).lower()
    if article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker"):
        return "06"
    if any(word in title for word in (
        "wildfire", "wildfires", "forest fire", "flood", "earthquake", "hurricane",
        "cyclone", "tsunami", "evacuation", "landslide", "volcanic eruption", "explosion",
        "disaster", "rescue operation", "mass casualty", "severe storm"
    )):
        return "01"
    person_story = any(word in title for word in (
        "ceo", "chief executive", "founder", "appointed", "appointment", "resigns",
        "steps down", "named as", "joins as", "executive", "chairman", "chairwoman",
        "president says", "minister says", "leader says"
    ))
    economy_story = any(word in title for word in (
        "inflation", "gas prices", "oil prices", "interest rate", "stock market",
        "shares rise", "shares fall", "earnings", "revenue", "gdp", "trade deficit",
        "price hike", "prices rise", "prices fall", "budget", "economy"
    )) or any(word in topic for word in ("business", "economy", "finance", "market", "trade"))
    tech_product_story = any(word in title for word in (
        "smartphone", "iphone", "android", "laptop", "ai model", "artificial intelligence",
        "app launches", "product launch", "new device", "software update", "chip launch",
        "apple", "google", "microsoft", "samsung", "openai", "tesla"
    ))
    if person_story and (any(x in topic for x in ("technology", "tech", "business", "entertainment")) or any(x in title for x in ("ceo", "founder", "executive", "appointed", "launch", "unveils", "announces", "announced"))):
        return "03"
    # Product and technology launches use the single-story report layout;
    # Format 03 is reserved for human/person-led corporate stories.
    if tech_product_story and any(x in topic for x in ("technology", "tech", "science")):
        return "05"
    if economy_story:
        return "02"
    return "05"


def summary_from_caption(caption, max_words=36):
    text = str(caption or "").strip()
    text = re.split(r"\n\s*(?:Source:|Original report:|(?:Illustrative )?image credit:|Image licence:|Image source:)", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(" ,;:-") + "…"
    text = text or "Read the original report for full details and context."
    # Validate any caption-derived text that will become visible on the image.
    return validate_english_text(text, "visible summary")


def add_pill(draw, box, text, fill=RED, text_fill=WHITE, max_font=28):
    draw.rounded_rectangle(box, radius=15, fill=fill)
    draw_centered(draw, box, text, font(max_font, True), text_fill)


def crop_photo(canvas, photo_info, box, category="GLOBAL NEWS", fit="cover"):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if photo_info and isinstance(photo_info.get("image"), Image.Image):
        photo = ImageOps.fit(photo_info["image"], (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        canvas.paste(photo.convert("RGBA"), (x1, y1))
        return True
    # Clearly labelled, original vector fallback.
    fallback = make_illustration(w, h, category)
    canvas.paste(fallback, (x1, y1))
    # Callers place the explicit illustration label where it cannot collide with the logo.
    return False


def make_illustration(width, height, category):
    im = Image.new("RGB", (width, height), (8, 21, 40))
    d = ImageDraw.Draw(im)
    # Rich, category-specific geometric illustration. Clearly not a photo.
    d.rectangle((0, 0, width, height), fill=(8, 21, 40))
    for i in range(7):
        x = int(width * i / 7)
        d.polygon([(x, 0), (min(width, x + width // 3), 0), (min(width, x + width // 6), height), (max(0, x - width // 8), height)], fill=(13 + i * 2, 39 + i * 3, 67 + i * 4))
    cx, cy = width // 2, height // 2
    if category in ("BUSINESS", "ECONOMY"):
        d.line((cx - width * .28, cy + height * .2, cx - width * .28, cy - height * .22), fill=WHITE, width=max(3, width // 180))
        d.line((cx - width * .28, cy + height * .2, cx + width * .27, cy + height * .2), fill=WHITE, width=max(3, width // 180))
        pts = [(cx - width*.22, cy+height*.1), (cx-width*.08, cy), (cx+width*.04, cy+height*.06), (cx+width*.22, cy-height*.17)]
        d.line(pts, fill=YELLOW, width=max(5, width // 65), joint="curve")
        d.polygon([(cx+width*.16, cy-height*.16),(cx+width*.24,cy-height*.21),(cx+width*.23,cy-height*.11)], fill=RED)
    elif category == "HEALTH":
        s = min(width, height) * .30
        d.rounded_rectangle((cx-s, cy-s, cx+s, cy+s), radius=int(s*.15), fill=RED)
        d.rectangle((cx-s*.22, cy-s*.72, cx+s*.22, cy+s*.72), fill=WHITE)
        d.rectangle((cx-s*.72, cy-s*.22, cx+s*.72, cy+s*.22), fill=WHITE)
    elif category == "TECHNOLOGY":
        s = min(width, height) * .27
        d.rounded_rectangle((cx-s, cy-s, cx+s, cy+s), radius=int(s*.12), outline=BLUE, width=max(4,width//80))
        d.rounded_rectangle((cx-s*.4, cy-s*.4, cx+s*.4, cy+s*.4), radius=10, fill=RED, outline=WHITE, width=max(2,width//180))
        for off in (-s*.55, 0, s*.55):
            d.line((cx-s*1.3, cy+off, cx-s, cy+off), fill=YELLOW, width=max(3,width//130))
            d.line((cx+s, cy+off, cx+s*1.3, cy+off), fill=YELLOW, width=max(3,width//130))
    elif category == "SCIENCE":
        s = min(width, height) * .30
        d.ellipse((cx-s*1.2,cy-s*.45,cx+s*1.2,cy+s*.45), outline=BLUE, width=max(4,width//100))
        d.ellipse((cx-s*.45,cy-s*1.2,cx+s*.45,cy+s*1.2), outline=WHITE, width=max(4,width//100))
        d.ellipse((cx-12,cy-12,cx+12,cy+12),fill=YELLOW)
    elif category == "SPORTS":
        s=min(width,height)*.28
        d.ellipse((cx-s,cy-s,cx+s,cy+s),outline=WHITE,width=max(4,width//100))
        d.polygon([(cx,cy-s*.35),(cx+s*.32,cy-s*.1),(cx+s*.2,cy+s*.32),(cx-s*.2,cy+s*.32),(cx-s*.32,cy-s*.1)],fill=YELLOW)
    elif category in ("WORLD NEWS", "GLOBAL NEWS"):
        d.rounded_rectangle((cx-width*.25,cy-height*.25,cx+width*.03,cy+height*.22),radius=16,fill=(18,59,95),outline=BLUE,width=max(3,width//120))
        d.rounded_rectangle((cx-width*.02,cy-height*.15,cx+width*.25,cy+height*.30),radius=16,fill=(50,23,37),outline=RED,width=max(3,width//120))
        for yy in (-.12,0,.12):
            d.line((cx-width*.20,cy+height*yy,cx-width*.04,cy+height*yy),fill=WHITE,width=max(3,width//110))
            d.line((cx+width*.02,cy+height*yy,cx+width*.19,cy+height*yy),fill=YELLOW,width=max(3,width//110))
    elif category in ("PEOPLE", "CORPORATE"):
        # Neutral person silhouette; never presented as a real individual.
        head = min(width, height) * .13
        d.ellipse((cx-head, cy-height*.28-head, cx+head, cy-height*.28+head), fill=(222, 194, 164))
        d.rounded_rectangle((cx-width*.20, cy-height*.10, cx+width*.20, cy+height*.35), radius=int(width*.08), fill=(21, 70, 109), outline=WHITE, width=max(3,width//150))
        d.polygon([(cx-width*.10,cy-height*.10),(cx,cy+height*.06),(cx+width*.10,cy-height*.10)],fill=RED)
    elif category in ("FOREST FIRES", "FLOOD EMERGENCY", "EARTHQUAKE UPDATE", "SEVERE STORM", "VOLCANIC ACTIVITY", "EVACUATION UPDATE", "EXPLOSION REPORT", "LANDSLIDE UPDATE", "TSUNAMI UPDATE", "DEVELOPING NEWS"):
        if category in ("FLOOD EMERGENCY", "TSUNAMI UPDATE"):
            for j in range(4):
                yy=cy-height*.20+j*height*.12
                d.arc((cx-width*.32,yy-height*.06,cx+width*.32,yy+height*.08),0,180,fill=BLUE if j%2==0 else YELLOW,width=max(4,width//65))
        elif category == "EARTHQUAKE UPDATE":
            pts=[(cx-width*.30,cy),(cx-width*.16,cy-height*.12),(cx-width*.07,cy+height*.18),(cx+width*.02,cy-height*.21),(cx+width*.12,cy+height*.08),(cx+width*.30,cy-height*.04)]
            d.line(pts,fill=YELLOW,width=max(6,width//55),joint="curve")
        else:
            for i, color in enumerate((RED, (255, 102, 25), YELLOW)):
                bw = width * (0.36 - i * .07)
                bh = height * (0.48 - i * .06)
                x1, x2 = cx - bw/2, cx + bw/2
                y1, y2 = cy - bh/2, cy + bh/2
                d.polygon([(cx,y1),(cx+bw*.20,y1+bh*.20),(x2,y1+bh*.43),(x2-width*.04,y2),(x1+width*.04,y2),(x1,y1+bh*.43),(cx-bw*.20,y1+bh*.20)],fill=color)
    else:
        # Distinct editorial geometry for uncategorized topics.
        d.ellipse((cx-width*.24,cy-height*.23,cx+width*.24,cy+height*.23),outline=BLUE,width=max(4,width//90))
        d.line((cx-width*.18,cy+height*.18,cx+width*.18,cy-height*.18),fill=YELLOW,width=max(5,width//70))
    return im


def get_photo_for_article(article):
    query = article.get("image_search_query") or article.get("title", "")
    return query_commons_image(query)


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
    date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y").upper()
    draw.text((date_x, y + 38), date, font=font(17, True), fill=muted)


def draw_template_01(article, post, photo):
    """Emergency/developing story with cinematic image and summary card."""
    canvas = gradient()
    d = ImageDraw.Draw(canvas)
    crop_photo(canvas, photo, (0, 0, WIDTH, 795), category=emergency_event_label(str(article.get("title", ""))))
    draw_photo_overlay(canvas, (0, 0, WIDTH, 795), 205)
    d = ImageDraw.Draw(canvas)
    brand(d, 36, 30, compact=True)
    title = str(article.get("title", ""))
    badge = emergency_event_label(title)
    add_pill(d, (55, 455, 420, 510), badge, RED, WHITE, 24)
    headline = post["headline"].strip()
    draw_wrapped(d, headline, (62, 530, 1015, 735), max_size=68, min_size=42, bold=True, max_lines=4)
    # White summary card overlaps image/body but stays below the headline.
    d.rounded_rectangle((55, 760, 1025, 1130), radius=22, fill=WHITE)
    summary = summary_from_caption(post.get("caption", ""), 36)
    draw_wrapped(d, summary, (90, 795, 990, 1090), max_size=31, min_size=23, bold=False, fill=INK, max_lines=7, line_multiplier=1.25)
    draw_footer(d, article.get("domain", ""), y=1190, dark=True)
    photo_label = "REFERENCE IMAGE" if photo else "ILLUSTRATIVE GRAPHIC"
    d.rounded_rectangle((705, 30, 1035, 77), radius=12, fill=INK)
    d.text((722, 41), photo_label, font=font(18, True), fill=YELLOW)
    return canvas


def draw_template_02(article, post, photo):
    """Business/economy card: photo top, navy copy panel, yellow story marker."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), PALE + (255,))
    d = ImageDraw.Draw(canvas)
    brand(d, 42, 28, compact=True)
    d.text((760, 48), datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y").upper(), font=font(20, True), fill=INK)
    crop_photo(canvas, photo, (45, 130, 1035, 650), category="BUSINESS")
    d = ImageDraw.Draw(canvas)
    photo_label = "REFERENCE PHOTO" if photo else "ILLUSTRATIVE GRAPHIC"
    d.rounded_rectangle((706, 145, 1016, 184), radius=10, fill=INK)
    d.text((720, 154), photo_label, font=font(16, True), fill=YELLOW)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((48, 588, 1032, 1040), radius=30, fill=NAVY)
    add_pill(d, (350, 555, 730, 622), "BUSINESS & ECONOMY", YELLOW, INK, 24)
    draw_wrapped(d, post["headline"], (92, 650, 990, 830), max_size=56, min_size=35, bold=True, max_lines=3)
    summary = summary_from_caption(post.get("caption", ""), 27)
    draw_wrapped(d, summary, (95, 845, 987, 1005), max_size=25, min_size=19, bold=False, fill=(220, 230, 241), max_lines=5, line_multiplier=1.18)
    d.rounded_rectangle((82, 1080, 998, 1186), radius=19, outline=NAVY, width=3, fill=WHITE)
    d.ellipse((110, 1112, 151, 1153), fill=NAVY)
    d.text((121, 1115), "→", font=font(26, True), fill=WHITE)
    draw_centered(d, (165, 1090, 890, 1178), "DETAILS IN CAPTION", font(26, True), NAVY)
    draw_footer(d, article.get("domain", ""), y=1240, dark=False)
    return canvas


def draw_template_03(article, post, photo):
    """People/corporate story: dark full-bleed visual, strong lower headline."""
    canvas = gradient()
    crop_photo(canvas, photo, (0, 0, WIDTH, HEIGHT), category="PEOPLE")
    draw_photo_overlay(canvas, (0, 350, WIDTH, HEIGHT), 225)
    d = ImageDraw.Draw(canvas)
    brand(d, 42, 35, compact=True)
    add_pill(d, (72, 595, 430, 653), "PEOPLE & CORPORATE", RED, WHITE, 24)
    draw_wrapped(d, post["headline"], (78, 680, 1000, 1000), max_size=62, min_size=40, bold=True, max_lines=4)
    summary = summary_from_caption(post.get("caption", ""), 24)
    draw_wrapped(d, summary, (80, 1010, 995, 1135), max_size=23, min_size=18, bold=False, fill=WHITE, max_lines=4, line_multiplier=1.2)
    tags = category_label(article)
    d.rounded_rectangle((80, 1152, 390, 1198), radius=18, fill=(27, 110, 157))
    draw_centered(d, (80, 1152, 390, 1198), tags, font(19, True), WHITE)
    draw_footer(d, article.get("domain", ""), y=1268, dark=True)
    photo_label = "REFERENCE IMAGE" if photo else "ILLUSTRATIVE GRAPHIC"
    d.rounded_rectangle((690, 42, 1035, 88), radius=12, fill=INK)
    d.text((708, 53), photo_label, font=font(18, True), fill=YELLOW)
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
    """Three-story editorial roundup; cannot run unless three story records exist."""
    canvas = gradient()
    d = ImageDraw.Draw(canvas)
    brand(d, 40, 30, compact=True)
    d.text((715, 46), datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y").upper(), font=font(19, True), fill=WHITE)
    d.text((52, 130), "TODAY'S", font=font(52, True), fill=WHITE)
    d.rounded_rectangle((48, 190, 675, 268), radius=9, fill=RED)
    d.text((72, 195), "HEADLINES", font=font(57, True), fill=WHITE)
    add_pill(d, (720, 205, 1025, 260), "TOP 3 STORIES", YELLOW, INK, 21)
    y = 300
    for idx, (story, photo) in enumerate(zip(stories, photos), start=1):
        row = (55, y, 1025, y + 235)
        d.rounded_rectangle(row, radius=18, fill=WHITE)
        crop_photo(canvas, photo, (68, y + 12, 338, y + 223), category=category_label(story))
        d = ImageDraw.Draw(canvas)
        visual_tag = "REFERENCE PHOTO" if photo else "ILLUSTRATION"
        d.rounded_rectangle((78, y + 20, 255, y + 48), radius=7, fill=INK)
        d.text((88, y + 25), visual_tag, font=font(12, True), fill=YELLOW)
        d.rounded_rectangle((318, y + 73, 390, y + 156), radius=10, fill=RED)
        draw_centered(d, (318, y + 73, 390, y + 156), f"{idx:02d}", font(32, True), WHITE)
        draw_wrapped(d, story["title"], (420, y + 25, 990, y + 126), max_size=28, min_size=20, bold=True, fill=INK, max_lines=3)
        story_summary = summary_from_caption(story.get("summary", story["title"]), 18)
        draw_wrapped(d, story_summary, (420, y + 132, 990, y + 213), max_size=19, min_size=15, bold=False, fill=(55, 65, 78), max_lines=3, line_multiplier=1.15)
        y += 245
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((45, 1055, 1035, 1200), radius=20, fill=RED)
    d.text((78, 1083), "FOLLOW NEWS SNAP", font=font(28, True), fill=WHITE)
    d.text((78, 1128), "For verified updates and context", font=font(22, False), fill=WHITE)
    d.text((48, 1250), "NEWS SNAP  •  GLOBAL NEWS", font=font(24, True), fill=WHITE)
    d.text((660, 1254), "REFERENCE VISUALS; CREDITS IN CAPTION", font=font(14, True), fill=YELLOW)
    return canvas


def draw_template_05(article, post, photo):
    """Single story report: red header, one lead image, white editorial report."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (242, 244, 247, 255))
    d = ImageDraw.Draw(canvas)
    brand(d, 45, 28, compact=True)
    d.rounded_rectangle((48, 132, 1032, 220), radius=9, fill=RED)
    d.text((85, 148), "NEWS REPORT", font=font(46, True), fill=WHITE)
    d.polygon([(900, 132), (935, 132), (905, 220), (870, 220)], fill=(255, 92, 100))
    d.polygon([(950, 132), (985, 132), (955, 220), (920, 220)], fill=(255, 92, 100))
    crop_photo(canvas, photo, (76, 248, 1004, 660), category=category_label(article))
    d = ImageDraw.Draw(canvas)
    photo_label = "REFERENCE IMAGE" if photo else "ILLUSTRATIVE GRAPHIC"
    d.rounded_rectangle((680, 260, 980, 300), radius=10, fill=INK)
    d.text((695, 270), photo_label, font=font(16, True), fill=YELLOW)
    date_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%A, %d %B %Y")
    d.text((88, 685), date_str, font=font(22, False), fill=(58, 67, 78))
    d.rounded_rectangle((82, 735, 94, 1127), radius=5, fill=RED)
    draw_wrapped(d, post["headline"], (125, 730, 990, 845), max_size=38, min_size=27, bold=True, fill=INK, max_lines=3)
    summary = summary_from_caption(post.get("caption", ""), 52)
    draw_wrapped(d, summary, (126, 850, 990, 1118), max_size=24, min_size=18, bold=False, fill=(33, 43, 54), max_lines=8, line_multiplier=1.24)
    d.rounded_rectangle((660, 1150, 990, 1215), radius=8, outline=(50, 62, 75), width=2, fill=PALE)
    draw_centered(d, (660, 1150, 990, 1215), article.get("domain", "SOURCE").upper()[:32], font(20, True), INK)
    d.text((48, 1260), "NEWS SNAP", font=font(27, True), fill=RED)
    return canvas


def draw_template_06(article, post, photo):
    """Verified statement/quote, only used with a confirmed quote object."""
    quote = validate_english_text(article.get("quote_text"), "verified quotation", 5, 45)
    speaker = validate_english_text(article.get("speaker"), "speaker name", 1, 8)
    canvas = gradient(top=(7, 52, 39), bottom=(4, 32, 25))
    d = ImageDraw.Draw(canvas)
    # Original paper-like quote panel.
    d.polygon([(70, 245), (955, 220), (1018, 1060), (88, 1110), (45, 575)], fill=(250, 250, 244))
    brand(d, 52, 34, compact=True)
    if photo:
        crop_photo(canvas, photo, (610, 330, 985, 1040))
        d = ImageDraw.Draw(canvas)
        # Mask the photo to a visually bounded portrait zone.
        d.rectangle((610, 330, 985, 1040), outline=(244, 244, 238), width=5)
    else:
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((650, 370, 950, 980), radius=22, fill=(22, 61, 49), outline=(100, 173, 128), width=3)
        d.ellipse((730, 450, 870, 590), fill=(212, 190, 162))
        d.rounded_rectangle((700, 590, 900, 900), radius=75, fill=(20, 42, 40))
        d.rounded_rectangle((660, 360, 955, 420), radius=10, fill=INK)
        d.text((680, 375), "ILLUSTRATIVE PORTRAIT", font=font(15, True), fill=YELLOW)
    if photo:
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((660, 360, 955, 420), radius=10, fill=INK)
        d.text((680, 375), "REFERENCE PORTRAIT", font=font(17, True), fill=YELLOW)
    d = ImageDraw.Draw(canvas)
    d.text((105, 300), "“", font=font(110, True), fill=GREEN)
    draw_wrapped(d, quote, (115, 420, 585, 755), max_size=38, min_size=25, bold=True, fill=(14, 48, 38), max_lines=8, line_multiplier=1.18)
    d.rounded_rectangle((105, 815, 590, 890), radius=7, fill=(31, 117, 69))
    draw_wrapped(d, speaker, (125, 820, 570, 880), max_size=30, min_size=21, bold=True, fill=WHITE, max_lines=2, line_multiplier=1.1)
    role = str(article.get("speaker_role", "")).strip()
    if role:
        role = validate_english_text(role, "speaker role", 1, 10)
        draw_wrapped(d, role, (110, 910, 585, 990), max_size=21, min_size=16, bold=False, fill=(36, 56, 48), max_lines=3)
    d.text((65, 1190), "NEWS SNAP", font=font(28, True), fill=WHITE)
    d.text((750, 1195), "PUBLIC STATEMENT", font=font(19, True), fill=(214, 236, 220))
    return canvas


def render_template(template_id, article, post):
    if template_id == "04":
        stories, roundup_post = load_roundup()
        photos = [query_commons_image(s.get("image_search_query") or s["title"]) for s in stories]
        image = draw_template_04(article, roundup_post, stories, photos)
        return image, roundup_post, photos

    if template_id == "06":
        # For a speaker card, only search by the speaker's name and require all
        # meaningful name tokens to match the Commons file metadata.
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
    if not LANGDETECT_AVAILABLE and os.environ.get("NEWS_SNAP_TEST_MODE") != "1":
        raise RuntimeError("langdetect is required; workflow must install dependencies")

    post_path = Path("post.json")
    article_path = Path("selected_article.json")
    if not post_path.is_file() or not article_path.is_file():
        raise FileNotFoundError("post.json and selected_article.json are both required")
    post = json.loads(post_path.read_text(encoding="utf-8"))
    article = json.loads(article_path.read_text(encoding="utf-8"))

    template_id = os.environ.get("NEWS_SNAP_FORCE_TEMPLATE") if os.environ.get("NEWS_SNAP_TEST_MODE") == "1" else None
    if template_id:
        template_id = template_id.zfill(2)
        if template_id not in {"01", "02", "03", "04", "05", "06"}:
            raise ValueError("NEWS_SNAP_FORCE_TEMPLATE must be 1 through 6")
    else:
        roundup_exists = Path("roundup.json").is_file() and Path("roundup_post.json").is_file()
        template_id = template_for(article, roundup_exists)

    if template_id == "04":
        roundup_post = json.loads(Path("roundup_post.json").read_text(encoding="utf-8"))
        post_for_render = roundup_post
        post_for_render["headline"] = validate_english_text(post_for_render.get("headline"), "roundup headline", 3, 12)
        post_for_render["curiosity_line"] = validate_english_text(post_for_render.get("curiosity_line"), "roundup curiosity", 3, 8)
    else:
        post_for_render = post
        post_for_render["headline"] = validate_english_text(post_for_render.get("headline"), "headline", 4, 12)
        post_for_render["curiosity_line"] = validate_english_text(post_for_render.get("curiosity_line"), "curiosity line", 3, 8)

    source = str(article.get("domain", "")).strip().lower()
    if not source or not re.fullmatch(r"[a-z0-9.-]+", source):
        raise ValueError("Invalid publisher domain; refusing image")

    image, rendered_post, photo_infos = render_template(template_id, article, post_for_render)
    caption_path = "roundup_post.json" if template_id == "04" else "post.json"
    for info in photo_infos:
        if info:
            annotate_image_credit(rendered_post, info, caption_path=caption_path)

    image = image.convert("RGB")
    image.save(OUTPUT, "JPEG", quality=94, optimize=True)
    with Image.open(OUTPUT) as check:
        check.verify()
    with Image.open(OUTPUT) as check:
        if check.size != (WIDTH, HEIGHT) or check.format != "JPEG":
            raise ValueError("Exported image failed format/dimension validation")
        if OUTPUT.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Image exceeds 8 MB")

    print(f"NEWS SNAP image created: {OUTPUT}")
    print(f"Template: {template_id}")
    print(f"Dimensions: {WIDTH}x{HEIGHT}")
    print(f"Source: {source}")
    print("Headline language and layout checks passed")
    print("Image source: licensed Wikimedia Commons image when available; otherwise labelled original graphic")
    if template_id == "04":
        print("Format 04 generated from exactly 3 roundup stories")
    if template_id == "06":
        print("Format 06 requires verified quote metadata in selected_article.json")


if __name__ == "__main__":
    main()

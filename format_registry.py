"""NEWS SNAP Format Registry — The Single Source of Truth for Approved Post Formats.

Contains exactly the six approved NEWS SNAP visual formats.
No seventh format, generic fallback, or arbitrary layout is permitted.
"""

from typing import Dict, Any

FORMAT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "01": {
        "id": "01",
        "name": "LIVE / DEVELOPING NEWS (Emergencies & Disasters)",
        "description": "High-impact card for natural disasters, emergencies, evacuations, and severe developing events.",
        "intended_topics": [
            "wildfire", "flood", "earthquake", "hurricane", "cyclone", "tsunami",
            "evacuation", "landslide", "volcano", "explosion", "severe storm", "disaster"
        ],
        "canvas_size": (1080, 1350),
        "aspect_ratio": "4:5",
        "background": "Deep dark navy (8, 14, 24)",
        "hero_image": "Top cover (0, 0, 1080, 840) with dark bottom overlay gradient",
        "branding": "Top-left red slash NEWS SNAP logo + red LIVE pill badge",
        "badges": "Red pill badge (60, 480, 420, 540) displaying emergency event label in white bold",
        "headline": "Bold two-tone headline (85, 560, 1020, 780), white top line + yellow accent, white vertical line on left",
        "supporting_text": "White rounded summary card (60, 810, 1020, 1220) with dark ink text (24-28px)",
        "footer": "Globe icon + NEWS SNAP | GLOBAL NEWS on left, DETAILS IN CAPTION -> on right",
        "colors": {
            "background": (8, 14, 24),
            "headline_white": (255, 255, 255),
            "headline_yellow": (255, 207, 45),
            "summary_card": (255, 255, 255),
            "summary_text": (15, 30, 54),
            "badge_fill": (230, 31, 45),
            "badge_text": (255, 255, 255),
        }
    },
    "02": {
        "id": "02",
        "name": "BUSINESS & ECONOMY (Markets & Money)",
        "description": "Editorial card for macroeconomic news, central bank decisions, market trends, inflation, commodities, and trade.",
        "intended_topics": [
            "business", "economy", "finance", "market", "trade", "inflation",
            "interest rate", "gdp", "revenue", "earnings", "stock market", "budget"
        ],
        "canvas_size": (1080, 1350),
        "aspect_ratio": "4:5",
        "background": "Dark navy container (10, 24, 45)",
        "hero_image": "Framed photo card top half with rounded top corners",
        "branding": "Compass NEWS SNAP logo top-left, date with globe icon top-right",
        "badges": "Yellow pill badge 'BREAKING NEWS' with dark ink text",
        "headline": "Bold two-tone uppercase headline: yellow top line + white bottom line",
        "supporting_text": "Clean summary in light blue-gray (210, 222, 235)",
        "call_to_action": "White rounded pill with navy border: DETAILS IN CAPTION",
        "footer": "Standardized bottom actions",
        "colors": {
            "background": (8, 16, 28),
            "card": (10, 24, 45),
            "headline_yellow": (255, 207, 45),
            "headline_white": (255, 255, 255),
            "badge_fill": (255, 207, 45),
            "badge_text": (0, 0, 0),
        }
    },
    "03": {
        "id": "03",
        "name": "PEOPLE & CORPORATE STORIES",
        "description": "Full-bleed portrait / corporate leadership card for CEO appointments, executive moves, prominent public figures.",
        "intended_topics": [
            "ceo", "chief executive", "founder", "appointment", "appointed",
            "resigns", "steps down", "named as", "chairman", "executive"
        ],
        "canvas_size": (1080, 1350),
        "aspect_ratio": "4:5",
        "background": "Dark navy / black canvas with monochrome portrait",
        "hero_image": "Monochrome / greyscale photo filling top 65% with dark bottom gradient",
        "branding": "Red slash NEWS SNAP logo top-left",
        "badges": "Red pill badge 'BREAKING NEWS' with white bold text",
        "headline": "Bold two-tone uppercase headline: white upper lines + yellow bottom line",
        "supporting_text": "Clean white summary paragraph",
        "category_tag": "3 colorful pills at bottom: Blue (Technology), Purple (Business), Green (Topic)",
        "footer": "Globe icon + NEWS SNAP | TECH NEWS on left, DETAILS IN CAPTION -> on right",
        "colors": {
            "background": (6, 12, 22),
            "headline_white": (255, 255, 255),
            "headline_yellow": (255, 207, 45),
            "supporting_text": (250, 252, 255),
            "badge_fill": (230, 31, 45),
        }
    },
    "04": {
        "id": "04",
        "name": "DAILY HEADLINES / ROUNDUP (Multiple Stories)",
        "description": "Curated three-story editorial roundup card summarizing the top three global news stories.",
        "requires_inputs": ["roundup.json", "roundup_post.json"],
        "canvas_size": (1080, 1350),
        "aspect_ratio": "4:5",
        "background": "Deep navy (8, 20, 38) with world map graphic",
        "header": "Red slash logo at (50, 45), calendar icon + date at (740, 60), 'TODAY\\'S' in white, red ribbon 'HEADLINES', red pill 'TOP 3 STORIES'",
        "story_rows": "3 slanted white cards, each with thumbnail, numbered red badge (01, 02, 03), bold dark title, and concise summary",
        "footer_cta": "Red notification banner with bell icon, follow message, and red button: FOLLOW NEWS SNAP FOR DAILY NEWS ->",
        "colors": {
            "background": (8, 20, 38),
            "card_fill": (255, 255, 255),
            "header_bar": (230, 31, 45),
            "pill_fill": (230, 31, 45),
        }
    },
    "05": {
        "id": "05",
        "name": "SINGLE-STORY NEWS REPORT (Detailed Update)",
        "description": "Clean editorial report card for major international developments, government actions, and technology announcements.",
        "intended_topics": [
            "world news", "politics", "diplomacy", "government", "treaty",
            "technology", "science", "health", "global news"
        ],
        "canvas_size": (1080, 1350),
        "aspect_ratio": "4:5",
        "background": "Dark navy canvas with clean white inner card",
        "branding": "Compass NEWS SNAP logo top-left (black NEWS, red SNAP)",
        "header": "Red ribbon banner 'BREAKING NEWS' with 3 white slanted hazard stripes '///'",
        "hero_image": "Framed lead photo with subtle rounded corners",
        "date_line": "Full date in dark gray",
        "vertical_accent": "Solid red vertical accent bar on left",
        "headline": "Bold black uppercase headline",
        "supporting_text": "Detailed summary paragraph in dark slate",
        "footer": "Dark navy footer bar with Globe icon + NEWS SNAP | WORLD NEWS",
        "colors": {
            "card_background": (255, 255, 255),
            "header_bar": (230, 31, 45),
            "accent_bar": (230, 31, 45),
            "headline": (0, 0, 0),
            "summary_text": (40, 45, 55),
        }
    },
    "06": {
        "id": "06",
        "name": "QUOTES & PUBLIC STATEMENTS",
        "description": "High-authority statement card featuring a verbatim verified quotation, speaker name, role, and portrait.",
        "requires_inputs": ["quote_verified=True", "quote_text", "speaker"],
        "canvas_size": (1080, 1350),
        "aspect_ratio": "4:5",
        "background": "Deep forest emerald textured canvas (7, 52, 39) to (4, 32, 25)",
        "paper_panel": "White torn-paper card overlay with ragged/torn right edge",
        "branding": "Red slash NEWS SNAP logo top-left",
        "quote_mark": "Large decorative quotation mark '“' in dark emerald green",
        "quote_text": "Verbatim quote in bold dark slate ink",
        "speaker_badge": "Dark emerald green pill with speaker name in white bold",
        "speaker_role": "Speaker title/role in dark slate",
        "portrait": "Portrait cutout / masked photo on right side",
        "footer": "Globe icon + NEWS SNAP | WORLD NEWS on left, DETAILS IN CAPTION -> on right",
        "colors": {
            "background": [(7, 52, 39), (4, 32, 25)],
            "quote_text": (18, 30, 24),
            "speaker_pill": (30, 126, 52),
            "quote_mark": (27, 94, 57),
        }
    }
}


def classify_format_for_article(article: dict, roundup_exists: bool = False) -> tuple[str, str]:
    """Select the exact approved NEWS SNAP format based on article metadata and rules.

    Returns (format_id, reason).
    """
    override = str(article.get("template_override", "")).strip().lower()
    if override in {"1", "01", "developing", "emergency", "c", "breaking_health", "health"}:
        return "01", "Selected via explicit template_override: Format 01 / Template C (Emergency & Breaking News)"
    if override in {"2", "02", "business", "economy", "b", "business_tech", "tech"}:
        return "02", "Selected via explicit template_override: Format 02 / Template B (Business & Technology)"
    if override in {"3", "03", "people", "corporate"}:
        return "03", "Selected via explicit template_override: Format 03 / Template B (People & Corporate)"
    if override in {"4", "04", "roundup", "daily_headlines"}:
        if not roundup_exists:
            raise ValueError("Format 04 requires roundup.json and roundup_post.json")
        return "04", "Selected via explicit template_override: Format 04 (Daily Headlines Roundup)"
    if override in {"5", "05", "report", "single_story", "a", "political", "politics"}:
        return "05", "Selected via explicit template_override: Format 05 / Template A (Political & News Report)"
    if override in {"6", "06", "quote", "statement"}:
        if not (article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker")):
            raise ValueError("Format 06 requires verified quote_text and speaker in selected_article.json")
        return "06", "Selected via explicit template_override: Format 06 (Verified Statement / Quote)"

    # Rule 1: Verified statement with quote and speaker -> Format 06
    if article.get("quote_verified") is True and article.get("quote_text") and article.get("speaker"):
        return "06", "Article contains source-verified quotation and speaker; qualifies for Format 06 (Verified Statement / Quote)"

    title = str(article.get("title", "")).lower()
    topic = str(article.get("classification", {}).get("topic", "")).lower()

    # Rule 2: Breaking News, Health & Outbreaks, Disasters, Emergencies -> Format 01 / Template C
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
    if any(k in title for k in health_keywords) or any(k in title for k in emergency_keywords) or any(k in topic for k in ("health", "emergency")):
        return "01", "Breaking health/emergency indicators detected; matched Format 01 / Template C (Breaking & Health News)"

    # Rule 3: People & Corporate leadership moves -> Format 03
    person_keywords = (
        "ceo", "chief executive", "founder", "appointed", "appointment",
        "resigns", "steps down", "named as", "joins as", "executive", "chairman"
    )
    if any(k in title for k in person_keywords):
        return "03", "Corporate leadership/executive move detected; matched Format 03 (People & Corporate Leadership)"

    # Rule 4: Business, macroeconomic trends, markets, inflation -> Format 02
    economy_keywords = (
        "inflation", "interest rate", "stock market", "shares rise", "shares fall",
        "earnings", "revenue", "gdp", "trade deficit", "price hike", "prices rise",
        "prices fall", "oil prices", "gas prices", "central bank", "budget"
    )
    if any(k in title for k in economy_keywords) or any(k in topic for k in ("business", "economy", "finance", "market")):
        return "02", "Economic/market indicators detected in headline or classification; matched Format 02 (Business & Economy)"

    # Rule 5: Standard global news, technology launches, politics, international reports -> Format 05
    return "05", "Standard international news report; matched Format 05 (Single Story News Report)"

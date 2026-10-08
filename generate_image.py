from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import math

from PIL import Image, ImageDraw, ImageFont, ImageFilter


WIDTH = 1080
HEIGHT = 1350

BG = (7, 14, 24)
WHITE = (248, 250, 252)
RED = (225, 25, 35)
YELLOW = (255, 210, 30)
BLUE = (20, 110, 190)
DARK = (10, 18, 30)
MUTED = (180, 190, 202)


def get_font(size, bold=False):
    candidates = []

    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):
    words = str(text).split()
    lines = []
    current = ""

    for word in words:
        test = word if not current else current + " " + word
        bbox = draw.textbbox((0, 0), test, font=font)

        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def draw_gradient_background(image):
    pixels = image.load()

    for y in range(HEIGHT):
        t = y / HEIGHT

        r = int(BG[0] * (1 - t) + 5 * t)
        g = int(BG[1] * (1 - t) + 20 * t)
        b = int(BG[2] * (1 - t) + 36 * t)

        for x in range(WIDTH):
            glow = max(0, 1 - math.hypot(x - 780, y - 300) / 850)

            pixels[x, y] = (
                min(255, int(r + 12 * glow)),
                min(255, int(g + 24 * glow)),
                min(255, int(b + 50 * glow)),
            )


def draw_cinematic_glow(base):
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)

    draw.ellipse(
        (650, 80, 1180, 610),
        fill=(25, 110, 220, 90)
    )

    draw.ellipse(
        (-180, 600, 420, 1180),
        fill=(220, 20, 35, 55)
    )

    glow = glow.filter(ImageFilter.GaussianBlur(90))
    base.alpha_composite(glow)


def draw_topic_visual(base, topic):
    draw = ImageDraw.Draw(base, "RGBA")
    topic = topic.lower()

    center_x = 800
    center_y = 650

    # Main circular visual
    for radius, alpha in [
        (250, 18),
        (215, 28),
        (180, 38),
    ]:
        draw.ellipse(
            (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            ),
            outline=(255, 255, 255, alpha),
            width=3,
        )

    # World / international
    if any(k in topic for k in ["world", "international", "war", "politics"]):
        draw.arc(
            (center_x - 175, center_y - 175,
             center_x + 175, center_y + 175),
            0, 360,
            fill=(80, 170, 255, 210),
            width=12,
        )

        draw.arc(
            (center_x - 105, center_y - 175,
             center_x + 105, center_y + 175),
            0, 360,
            fill=(120, 190, 255, 170),
            width=6,
        )

        draw.line(
            (center_x - 175, center_y,
             center_x + 175, center_y),
            fill=(120, 190, 255, 150),
            width=5,
        )

        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = center_x + 120 * math.cos(rad)
            y1 = center_y + 120 * math.sin(rad)
            x2 = center_x + 170 * math.cos(rad)
            y2 = center_y + 170 * math.sin(rad)

            draw.line(
                (x1, y1, x2, y2),
                fill=(255, 210, 30, 170),
                width=4,
            )

    # Health
    elif "health" in topic or "medical" in topic:
        draw.rounded_rectangle(
            (center_x - 120, center_y - 120,
             center_x + 120, center_y + 120),
            radius=35,
            fill=(220, 30, 45, 150),
            outline=(255, 255, 255, 180),
            width=5,
        )

        draw.rectangle(
            (center_x - 28, center_y - 85,
             center_x + 28, center_y + 85),
            fill=(255, 255, 255, 235),
        )

        draw.rectangle(
            (center_x - 85, center_y - 28,
             center_x + 85, center_y + 28),
            fill=(255, 255, 255, 235),
        )

    # Technology
    elif "tech" in topic or "technology" in topic:
        draw.rounded_rectangle(
            (center_x - 170, center_y - 105,
             center_x + 170, center_y + 105),
            radius=25,
            outline=(70, 180, 255, 230),
            width=8,
        )

        draw.line(
            (center_x - 70, center_y + 140,
             center_x + 70, center_y + 140),
            fill=(255, 255, 255, 190),
            width=10,
        )

        draw.line(
            (center_x, center_y + 105,
             center_x, center_y + 140),
            fill=(255, 255, 255, 190),
            width=8,
        )

        draw.arc(
            (center_x - 95, center_y - 55,
             center_x + 95, center_y + 55),
            200,
            340,
            fill=(255, 210, 30, 220),
            width=8,
        )

    # Business / economy
    elif any(k in topic for k in ["business", "economy", "market", "finance"]):
        points = [
            (center_x - 170, center_y + 90),
            (center_x - 70, center_y + 10),
            (center_x + 20, center_y + 40),
            (center_x + 110, center_y - 70),
            (center_x + 175, center_y - 130),
        ]

        draw.line(
            points,
            fill=(60, 210, 120, 230),
            width=12,
            joint="curve",
        )

        for x, y in points:
            draw.ellipse(
                (x - 12, y - 12, x + 12, y + 12),
                fill=(255, 255, 255, 240),
            )

    # Generic breaking-news visual
    else:
        draw.polygon(
            [
                (center_x - 180, center_y + 120),
                (center_x - 110, center_y - 140),
                (center_x + 30, center_y - 80),
                (center_x + 180, center_y - 170),
                (center_x + 115, center_y + 130),
            ],
            fill=(225, 25, 35, 130),
            outline=(255, 255, 255, 170),
        )

        draw.line(
            (center_x - 145, center_y + 70,
             center_x + 145, center_y - 105),
            fill=(255, 210, 30, 230),
            width=10,
        )


def draw_text_box(draw, xy, text, font, fill, outline=None, radius=16, padding=18):
    x1, y1, x2, y2 = xy

    draw.rounded_rectangle(
        xy,
        radius=radius,
        fill=fill,
        outline=outline,
        width=3 if outline else 1,
    )

    draw.text(
        (x1 + padding, y1 + padding),
        text,
        font=font,
        fill=WHITE,
    )


def main():
    post_path = Path("post.json")
    article_path = Path("selected_article.json")

    if not post_path.exists():
        raise FileNotFoundError("post.json not found")

    if not article_path.exists():
        raise FileNotFoundError("selected_article.json not found")

    post = json.loads(post_path.read_text(encoding="utf-8"))
    article = json.loads(article_path.read_text(encoding="utf-8"))

    headline = post.get("headline", "").strip()
    curiosity = post.get("curiosity_line", "").strip()
    hashtags = post.get("hashtags", [])
    source = article.get("domain", "Unknown source")
    topic = article.get("classification", {}).get("topic", "World News")
    reason = article.get("classification", {}).get("reason", "")

    image = Image.new("RGBA", (WIDTH, HEIGHT), BG + (255,))
    draw_gradient_background(image)
    draw_cinematic_glow(image)
    draw_topic_visual(image, topic)

    draw = ImageDraw.Draw(image, "RGBA")

    # Fonts
    logo_font = get_font(62, bold=True)
    category_font = get_font(30, bold=True)
    headline_font = get_font(66, bold=True)
    curiosity_font = get_font(28, bold=True)
    fact_title_font = get_font(26, bold=True)
    fact_text_font = get_font(21, bold=False)
    source_font = get_font(21, bold=True)

    # ---------------------------------------------------------
    # TOP: NEWS SNAP
    # ---------------------------------------------------------
    draw.rounded_rectangle(
        (35, 30, 300, 145),
        radius=22,
        fill=(0, 0, 0, 185),
        outline=(240, 240, 240, 220),
        width=3,
    )

    draw.text(
        (58, 42),
        "NEWS",
        font=logo_font,
        fill=WHITE,
    )

    draw.text(
        (58, 93),
        "SNAP",
        font=logo_font,
        fill=RED,
    )

    # Category
    category = f"BREAKING {str(topic).upper()[:22]}"

    draw.rounded_rectangle(
        (330, 48, 755, 120),
        radius=18,
        fill=(220, 25, 35, 235),
    )

    draw.text(
        (355, 67),
        category,
        font=category_font,
        fill=WHITE,
    )

    # ---------------------------------------------------------
    # HEADLINE
    # ---------------------------------------------------------
    headline_lines = wrap_text(
        draw,
        headline,
        headline_font,
        1000,
    )

    headline_lines = headline_lines[:4]

    y = 175

    for line in headline_lines:
        draw.text(
            (40, y),
            line,
            font=headline_font,
            fill=WHITE,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 130),
        )
        y += 76

    # ---------------------------------------------------------
    # CURIOSITY BAR
    # ---------------------------------------------------------
    curiosity = curiosity or "WHAT HAPPENS NEXT?"

    bar_y1 = 500
    bar_y2 = 585

    draw.rounded_rectangle(
        (35, bar_y1, 1045, bar_y2),
        radius=18,
        fill=(225, 25, 35, 225),
    )

    curiosity_lines = wrap_text(
        draw,
        curiosity,
        curiosity_font,
        990,
    )[:2]

    cy = bar_y1 + 13

    for line in curiosity_lines:
        draw.text(
            (58, cy),
            line,
            font=curiosity_font,
            fill=WHITE,
        )
        cy += 34

    # ---------------------------------------------------------
    # MAIN VISUAL LABEL
    # ---------------------------------------------------------
    draw.rounded_rectangle(
        (45, 625, 400, 675),
        radius=12,
        fill=(0, 0, 0, 160),
    )

    draw.text(
        (62, 638),
        "NEWS SNAP • LIVE",
        font=get_font(22, bold=True),
        fill=YELLOW,
    )

    # ---------------------------------------------------------
    # FACT CARDS
    # ---------------------------------------------------------
    fact_y1 = 860
    fact_y2 = 1085

    cards = [
        (
            "TOPIC",
            str(topic)[:70],
        ),
        (
            "WHY IT MATTERS",
            str(reason)[:110] if reason else "Major news development",
        ),
        (
            "SOURCE",
            str(source)[:70],
        ),
    ]

    card_width = 322
    gap = 22

    for i, (title, text) in enumerate(cards):
        x1 = 35 + i * (card_width + gap)
        x2 = x1 + card_width

        draw.rounded_rectangle(
            (x1, fact_y1, x2, fact_y2),
            radius=20,
            fill=(5, 15, 27, 225),
            outline=(70, 95, 120, 190),
            width=2,
        )

        draw.text(
            (x1 + 20, fact_y1 + 18),
            title,
            font=fact_title_font,
            fill=YELLOW if title != "SOURCE" else WHITE,
        )

        wrapped = wrap_text(
            draw,
            text,
            fact_text_font,
            card_width - 40,
        )[:6]

        ty = fact_y1 + 65

        for line in wrapped:
            draw.text(
                (x1 + 20, ty),
                line,
                font=fact_text_font,
                fill=WHITE if title != "SOURCE" else MUTED,
            )
            ty += 29

    # ---------------------------------------------------------
    # BOTTOM SOURCE / DATE
    # ---------------------------------------------------------
    india_now = datetime.now(
        ZoneInfo("Asia/Kolkata")
    )

    date_text = india_now.strftime("%d %b %Y").upper()

    draw.line(
        (35, 1130, 1045, 1130),
        fill=(255, 255, 255, 100),
        width=2,
    )

    draw.text(
        (45, 1160),
        f"SOURCE: {source.upper()}",
        font=source_font,
        fill=WHITE,
    )

    draw.text(
        (770, 1160),
        date_text,
        font=source_font,
        fill=MUTED,
    )

    draw.text(
        (45, 1215),
        "NEWS SNAP • GLOBAL NEWS",
        font=get_font(24, bold=True),
        fill=RED,
    )

    # ---------------------------------------------------------
    # Small hashtag line
    # ---------------------------------------------------------
    tag_text = " ".join(hashtags[:4])

    if tag_text:
        draw.text(
            (45, 1255),
            tag_text[:95],
            font=get_font(19, bold=False),
            fill=MUTED,
        )

    output = "news_snap_post.jpg"
    image.convert("RGB").save(
        output,
        quality=95,
        optimize=True,
    )

    print(f"NEWS SNAP image created: {output}")
    print(f"Size: {WIDTH}x{HEIGHT}")


if __name__ == "__main__":
    main()

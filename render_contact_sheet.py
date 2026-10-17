"""Render realistic fixtures for all six approved NEWS SNAP formats and assemble a contact sheet.

Verifies visual hierarchy, typography, colors, branding, and absence of text clipping or overlap
across Formats 01, 02, 03, 04, 05, and 06.
"""

import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import generate_image


def get_font(size: int, bold: bool = True):
    return generate_image.font(size, bold=bold)


def render_all_six_formats():
    output_dir = Path("previews")
    output_dir.mkdir(exist_ok=True)

    # 1. Format 01: Emergency and Developing News
    art_01 = {
        "title": "Severe Coastal Wildfire Prompts Mass Evacuations in Regional Park",
        "domain": "reuters.com",
        "url": "https://reuters.com/emergency/wildfire",
        "classification": {"importance": "MAJOR", "topic": "Emergency"}
    }
    post_01 = {
        "headline": "Severe Wildfire Prompts Mass Evacuations in Regional Park",
        "curiosity_line": "Emergency crews battle spreading blaze",
        "caption": "Firefighters and emergency response teams are responding to spreading wildfires across the regional park as dry conditions persist. Read the original report for full details and context.\n\nSource: reuters.com\nOriginal report: https://reuters.com/emergency/wildfire\n\n#NewsSnap #Wildfire #Emergency",
        "hashtags": ["#NewsSnap", "#Wildfire", "#Emergency"]
    }
    img_01, _, _ = generate_image.render_approved_format("01", art_01, post_01)
    img_01 = img_01.convert("RGB")
    path_01 = output_dir / "preview_format_01.jpg"
    img_01.save(path_01, "JPEG", quality=95)

    # 2. Format 02: Business and Economy
    art_02 = {
        "title": "Central Bank Holds Benchmark Interest Rate Steady as Inflation Pressures Ease",
        "domain": "ft.com",
        "url": "https://ft.com/economy/rates",
        "classification": {"importance": "MAJOR", "topic": "Business"}
    }
    post_02 = {
        "headline": "Central Bank Holds Benchmark Interest Rate Steady",
        "curiosity_line": "Inflation cooling drives monetary policy decision",
        "caption": "Policymakers announced that the benchmark interest rate will remain unchanged following economic data indicating moderating price pressures. Read the original report for full details and context.\n\nSource: ft.com\nOriginal report: https://ft.com/economy/rates\n\n#NewsSnap #Economy #Finance",
        "hashtags": ["#NewsSnap", "#Economy", "#Finance"]
    }
    img_02, _, _ = generate_image.render_approved_format("02", art_02, post_02)
    img_02 = img_02.convert("RGB")
    path_02 = output_dir / "preview_format_02.jpg"
    img_02.save(path_02, "JPEG", quality=95)

    # 3. Format 03: People and Corporate Leadership
    art_03 = {
        "title": "Global Technology Board Appoints New Chief Executive to Lead Expansion",
        "domain": "bloomberg.com",
        "url": "https://bloomberg.com/leadership/ceo",
        "classification": {"importance": "MAJOR", "topic": "People"}
    }
    post_03 = {
        "headline": "Board Appoints New Chief Executive for Global Expansion",
        "curiosity_line": "Executive leadership transition effective immediately",
        "caption": "The board of directors confirmed executive leadership changes to oversee strategic international operations. Read the original report for full details and context.\n\nSource: bloomberg.com\nOriginal report: https://bloomberg.com/leadership/ceo\n\n#NewsSnap #Leadership #Technology",
        "hashtags": ["#NewsSnap", "#Leadership", "#Technology"]
    }
    img_03, _, _ = generate_image.render_approved_format("03", art_03, post_03)
    img_03 = img_03.convert("RGB")
    path_03 = output_dir / "preview_format_03.jpg"
    img_03.save(path_03, "JPEG", quality=95)

    # 4. Format 04: Daily Headlines Roundup (3 stories)
    roundup = {
        "stories": [
            {
                "title": "Global Leaders Agree on Renewable Energy Goals",
                "domain": "reuters.com",
                "url": "https://reuters.com/energy/goals",
                "summary": "Nations commit to tripling clean energy capacity by 2030."
            },
            {
                "title": "Central Bank Holds Benchmark Interest Rate Steady",
                "domain": "bloomberg.com",
                "url": "https://bloomberg.com/economy/rates",
                "summary": "Policymakers maintain interest rates following inflation reports."
            },
            {
                "title": "Space Agency Launches Atmospheric Research Mission",
                "domain": "bbc.com",
                "url": "https://bbc.com/science/space",
                "summary": "New satellite will track worldwide climate and greenhouse gases."
            }
        ]
    }
    roundup_post = {
        "headline": "TODAY'S TOP 3 STORIES",
        "curiosity_line": "Key developments across energy, economy and science",
        "format": "04",
        "caption": "NEWS SNAP roundup of today's top stories. #NewsSnap\n\n1. Energy goals — reuters.com\n2. Rate steady — bloomberg.com\n3. Space mission — bbc.com",
        "hashtags": ["#NewsSnap", "#DailyBriefing", "#GlobalNews"]
    }
    p1 = Path("roundup.json")
    p2 = Path("roundup_post.json")
    p1.write_text(json.dumps(roundup), encoding="utf-8")
    p2.write_text(json.dumps(roundup_post), encoding="utf-8")
    try:
        img_04, _, _ = generate_image.render_approved_format("04", {}, roundup_post)
        img_04 = img_04.convert("RGB")
        path_04 = output_dir / "preview_format_04.jpg"
        img_04.save(path_04, "JPEG", quality=95)
    finally:
        if p1.is_file():
            p1.unlink()
        if p2.is_file():
            p2.unlink()

    # 5. Format 05: Single-Story News Report
    art_05 = {
        "title": "European Union Council Adopts Standardized Carbon Border Regulatory Framework",
        "domain": "reuters.com",
        "url": "https://reuters.com/world/eu/carbon-rules",
        "classification": {"importance": "MAJOR", "topic": "Government"}
    }
    post_05 = {
        "headline": "European Union Council Adopts Standardized Carbon Border Rules",
        "curiosity_line": "Member states approve landmark environmental regulations",
        "caption": "Member states finalized approval for standardized cross-border emissions guidelines scheduled to take effect across European industries. Read the original report for full details and context.\n\nSource: reuters.com\nOriginal report: https://reuters.com/world/eu/carbon-rules\n\n#NewsSnap #WorldNews #ClimatePolicy",
        "hashtags": ["#NewsSnap", "#WorldNews", "#ClimatePolicy"]
    }
    img_05, _, _ = generate_image.render_approved_format("05", art_05, post_05)
    img_05 = img_05.convert("RGB")
    path_05 = output_dir / "preview_format_05.jpg"
    img_05.save(path_05, "JPEG", quality=95)

    # 6. Format 06: Verified Quotes and Public Statements
    art_06 = {
        "title": "Secretary-General Addresses Peace Summit on Multilateral Security",
        "domain": "reuters.com",
        "url": "https://reuters.com/world/un/peace-summit",
        "quote_verified": True,
        "quote_text": "Peace is not merely the absence of conflict, but the presence of justice and shared human dignity.",
        "speaker": "António Guterres",
        "speaker_role": "United Nations Secretary-General",
        "classification": {"importance": "MAJOR", "topic": "Diplomacy"}
    }
    post_06 = {
        "headline": "UN Chief Delivers Key Address on Global Security",
        "curiosity_line": "International cooperation urged at multilateral summit",
        "caption": "During opening remarks at the multilateral summit, the Secretary-General underscored international commitments to collective security. Read the original report for full context.\n\nSource: reuters.com\nOriginal report: https://reuters.com/world/un/peace-summit\n\n#NewsSnap #Diplomacy #UnitedNations",
        "hashtags": ["#NewsSnap", "#Diplomacy", "#UnitedNations"]
    }
    img_06, _, _ = generate_image.render_approved_format("06", art_06, post_06)
    img_06 = img_06.convert("RGB")
    path_06 = output_dir / "preview_format_06.jpg"
    img_06.save(path_06, "JPEG", quality=95)

    rendered_cards = [
        ("Format 01: Emergency & Developing News", img_01),
        ("Format 02: Business & Economy", img_02),
        ("Format 03: People & Corporate Leadership", img_03),
        ("Format 04: Daily Headlines Roundup", img_04),
        ("Format 05: Single-Story News Report", img_05),
        ("Format 06: Verified Quotes & Statements", img_06),
    ]

    # Create 3 columns x 2 rows Contact Sheet
    card_w = 720
    card_h = 900
    cols = 3
    rows = 2
    pad = 40
    label_h = 36
    header_h = 110

    sheet_w = cols * card_w + (cols + 1) * pad
    sheet_h = rows * (card_h + label_h + 12) + (rows + 1) * pad + header_h

    sheet = Image.new("RGB", (sheet_w, sheet_h), (8, 16, 28))
    d = ImageDraw.Draw(sheet)

    # Header
    d.text((pad, 30), "NEWS SNAP", font=get_font(40, bold=True), fill=(230, 31, 45))
    d.text((pad + 260, 38), "— COMPREHENSIVE SIX-FORMAT CONTACT SHEET", font=get_font(28, bold=True), fill=(255, 255, 255))
    d.text((pad + 260, 74), "1080x1350 Canvas Dimensions • Strict Editorial Quality Gate & Brand Hierarchy", font=get_font(18, bold=False), fill=(140, 165, 195))

    for idx, (title_label, card_img) in enumerate(rendered_cards):
        r = idx // cols
        c = idx % cols
        x = pad + c * (card_w + pad)
        y = header_h + pad + r * (card_h + label_h + 12 + pad)

        # Draw label pill cleanly above card in the margin
        lbl_bbox = d.textbbox((0, 0), title_label, font=get_font(16, bold=True))
        lbl_w = lbl_bbox[2] - lbl_bbox[0] + 28
        d.rounded_rectangle((x, y, x + lbl_w, y + label_h), radius=10, fill=(16, 32, 58), outline=(60, 110, 175), width=1)
        d.text((x + 14, y + 8), title_label, font=get_font(16, bold=True), fill=(255, 255, 255))

        card_y = y + label_h + 8
        thumb = card_img.resize((card_w, card_h), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x, card_y))

        # Subtle crisp border around card
        d.rectangle((x, card_y, x + card_w, card_y + card_h), outline=(40, 70, 110), width=2)

    contact_path = Path("contact_sheet.jpg")
    sheet.save(contact_path, "JPEG", quality=95)
    print(f"[OK] Generated contact sheet: {contact_path.resolve()} ({sheet_w}x{sheet_h})")

    # Copy to artifact directory if available
    artifact_dir = Path(r"C:\Users\alokk\.gemini\antigravity\brain\57b776a3-405d-4e91-bc68-293dab3f236c")
    if artifact_dir.is_dir():
        for f in output_dir.glob("*.jpg"):
            dest = artifact_dir / f.name
            dest.write_bytes(f.read_bytes())
        (artifact_dir / "contact_sheet.jpg").write_bytes(sheet_bytes := contact_path.read_bytes())
        print(f"[OK] Copied contact sheet and previews to artifact directory: {artifact_dir}")

    return contact_path


build_contact_sheet = render_all_six_formats

if __name__ == "__main__":
    render_all_six_formats()


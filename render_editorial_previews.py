"""Render the three redesigned NEWS SNAP editorial templates and inspect output."""

import json
from pathlib import Path
from PIL import Image

import generate_image


def generate_previews():
    out_dir = Path("previews")
    out_dir.mkdir(exist_ok=True)

    # 1. Template A — Political News (Rahul Gandhi / Parliament)
    art_a = {
        "title": "Rahul Gandhi Leads Opposition Protest at Parliament Over Economic Policy",
        "domain": "thehindu.com",
        "url": "https://thehindu.com/news/national/rahul-gandhi-parliament-protest",
        "classification": {"importance": "MAJOR", "topic": "Politics"}
    }
    post_a = {
        "headline": "OPPOSITION PROTESTS AT PARLIAMENT OVER ECONOMIC POLICY",
        "summary": "Senior opposition leaders and MPs held demonstrations at Parliament today, calling for targeted fiscal relief, job guarantees, and structural inflation controls.",
        "caption": "Opposition lawmakers gathered outside Parliament in New Delhi today to stage demonstrations regarding macroeconomic policies.\n\nSource: thehindu.com\n\n#NewsSnap #Politics #Parliament",
        "hashtags": ["#NewsSnap", "#Politics", "#Parliament"]
    }
    img_a, post_a_rendered, photos_a = generate_image.render_approved_format("political", art_a, post_a)
    img_a = img_a.convert("RGB")
    path_a = out_dir / "preview_template_a_political.jpg"
    img_a.save(path_a, "JPEG", quality=95, optimize=True)
    print(f"Template A rendered: {path_a} (size: {img_a.size}, photos: {len(photos_a)})")

    # 2. Template B — Business & Technology News (Elon Musk / Tesla)
    art_b = {
        "title": "Elon Musk Details Next-Gen Autonomous Architecture and Vehicle Roadmap",
        "domain": "reuters.com",
        "url": "https://reuters.com/technology/musk-autonomous-architecture",
        "classification": {"importance": "MAJOR", "topic": "Technology"}
    }
    post_b = {
        "headline": "ELON MUSK DETAILS NEXT-GEN AUTONOMOUS ARCHITECTURE",
        "summary": "Tesla unveiled new specifications for its next-generation compute platform, targeting high-efficiency inference silicon and mass-production electric vehicles.",
        "caption": "During an executive briefing, Elon Musk confirmed new architectural advancements in autonomous compute hardware and vehicle manufacturing.\n\nSource: reuters.com\n\n#NewsSnap #Tesla #Technology",
        "hashtags": ["#NewsSnap", "#Tesla", "#Technology"]
    }
    img_b, post_b_rendered, photos_b = generate_image.render_approved_format("business_tech", art_b, post_b)
    img_b = img_b.convert("RGB")
    path_b = out_dir / "preview_template_b_business_tech.jpg"
    img_b.save(path_b, "JPEG", quality=95, optimize=True)
    print(f"Template B rendered: {path_b} (size: {img_b.size}, photos: {len(photos_b)})")

    # 3. Template C — Breaking News & Health News (WHO Avian Flu Advisory)
    art_c = {
        "title": "WHO Issues Advisory on Global Avian Influenza Surveillance Protocols",
        "domain": "who.int",
        "url": "https://who.int/news/item/avian-influenza-surveillance",
        "classification": {"importance": "MAJOR", "topic": "Health"}
    }
    post_c = {
        "headline": "WHO ISSUES ADVISORY ON GLOBAL SURVEILLANCE PROTOCOLS",
        "summary": "The World Health Organization released updated laboratory guidance today, advising national health agencies to maintain robust monitoring across regional wildlife contacts.",
        "caption": "The World Health Organization published enhanced diagnostic recommendations for international public health laboratories. Read the official advisory for guidance.\n\nSource: who.int\n\n#NewsSnap #Health #WHO",
        "hashtags": ["#NewsSnap", "#Health", "#WHO"]
    }
    img_c, post_c_rendered, photos_c = generate_image.render_approved_format("breaking_health", art_c, post_c)
    img_c = img_c.convert("RGB")
    path_c = out_dir / "preview_template_c_breaking_health.jpg"
    img_c.save(path_c, "JPEG", quality=95, optimize=True)
    print(f"Template C rendered: {path_c} (size: {img_c.size}, photos: {len(photos_c)})")

    return path_a, path_b, path_c


if __name__ == "__main__":
    generate_previews()

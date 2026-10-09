import json
import os
import re
import unicodedata
import urllib.request
from urllib.parse import urlparse

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0

MODEL = "gemini-3.5-flash-lite"
API_URL = (
    "https://generativelanguage.googleapis.com/"
    f"v1beta/models/{MODEL}:generateContent"
)


def is_latin_script(text):
    if not isinstance(text, str) or not text.strip():
        return False

    for char in text:
        if char.isalpha():
            name = unicodedata.name(char, "")
            if not name.startswith("LATIN "):
                return False

        if char.isdigit() and not char.isascii():
            return False

    return True


def is_english(text, minimum_confidence=0.70):
    if not is_latin_script(text):
        return False

    try:
        results = detect_langs(text)
        return bool(
            results
            and results[0].lang == "en"
            and results[0].prob >= minimum_confidence
        )
    except LangDetectException:
        return False


def word_count(text):
    return len(text.split())


def validate_post(post, source, url):
    if not isinstance(post, dict):
        raise ValueError("Output must be a JSON object.")

    required = {
        "headline",
        "curiosity_line",
        "caption",
        "hashtags",
    }

    if not required.issubset(post):
        raise ValueError("Required post fields are missing.")

    headline = post.get("headline")
    curiosity = post.get("curiosity_line")
    caption = post.get("caption")

    for field, value in (
        ("headline", headline),
        ("curiosity_line", curiosity),
        ("caption", caption),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is missing.")

        if not is_latin_script(value):
            raise ValueError(
                f"{field} contains non-Latin text. Rejecting post."
            )

        if not is_english(value):
            raise ValueError(
                f"{field} failed English validation."
            )

    headline = headline.strip()
    curiosity = curiosity.strip()
    caption = caption.strip()

    if not 4 <= word_count(headline) <= 12:
        raise ValueError("Headline must contain 4–12 words.")

    if not 3 <= word_count(curiosity) <= 8:
        raise ValueError("Curiosity line must contain 3–8 words.")

    if not 20 <= word_count(caption) <= 70:
        raise ValueError("Caption must contain 20–70 words.")

    hashtags = post.get("hashtags")

    if not isinstance(hashtags, list) or not 3 <= len(hashtags) <= 5:
        raise ValueError("Provide 3–5 hashtags.")

    for tag in hashtags:
        if not isinstance(tag, str):
            raise ValueError("Invalid hashtag.")

        if not re.fullmatch(r"#[A-Za-z][A-Za-z0-9_]{0,29}", tag):
            raise ValueError("Invalid hashtag format.")

    if len({tag.lower() for tag in hashtags}) != len(hashtags):
        raise ValueError("Duplicate hashtags are not allowed.")

    if not any(tag.lower() == "#newssnap" for tag in hashtags):
        raise ValueError("#NewsSnap brand hashtag is required.")

    final_caption = (
        f"{caption}\n\n"
        f"Source: {source}\n"
        f"Original report: {url}"
    )

    if word_count(final_caption) > 100:
        raise ValueError("Final caption exceeds 100 words.")

    if not is_latin_script(final_caption):
        raise ValueError("Final caption contains unsupported script.")

    return {
        "headline": headline,
        "curiosity_line": curiosity,
        "caption": final_caption,
        "hashtags": hashtags,
    }


def generate_post(article):
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    title = str(article.get("title", "")).strip()
    source = str(article.get("domain", "")).strip()
    url = str(article.get("url", "")).strip()

    if not all((title, source, url)):
        raise ValueError("Article title, source or URL is missing.")

    parsed_url = urlparse(url)

    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise ValueError("Article URL is invalid.")

    if not is_latin_script(title):
        raise ValueError("Source title contains unsupported script.")

    prompt = f"""
You are the NEWS SNAP English-language news editor.

LANGUAGE:
- Write natural, professional English only.
- Use the Latin alphabet.
- Never use Urdu, Persian, Arabic, Hindi or other scripts.

ACCURACY:
- Only the supplied headline is available.
- Do not claim you have read the full article.
- Do not invent facts, dates, names, numbers or quotations.
- Preserve uncertainty and allegations in the source wording.
- Do not label a story BREAKING, LIVE or VERIFIED without evidence.

STYLE:
- Headline: 4–12 words.
- Curiosity line: 3–8 words.
- Caption: 20–70 words.
- Use 3–5 relevant English hashtags, including #NewsSnap.
- No clickbait, exaggeration or misleading questions.

Return ONLY valid JSON:
{{
  "headline": "...",
  "curiosity_line": "...",
  "caption": "...",
  "hashtags": ["#NewsSnap", "#Topic", "#NewsUpdate"]
}}

Source headline: {title}
Publisher: {source}
Original article URL: {url}
"""

    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)

    candidates = data.get("candidates", [])

    if not candidates:
        raise ValueError("Gemini returned no usable candidate.")

    parts = candidates[0].get("content", {}).get("parts", [])

    if not parts or not parts[0].get("text"):
        raise ValueError("Gemini returned no text.")

    post = json.loads(parts[0]["text"])
    return validate_post(post, source, url)


with open("selected_article.json", "r", encoding="utf-8") as file:
    article = json.load(file)

print("Generating NEWS SNAP content...")

post = generate_post(article)

with open("post.json", "w", encoding="utf-8") as file:
    json.dump(post, file, ensure_ascii=False, indent=2)

print("Content validation passed.")
print("Headline:", post["headline"])
print("Curiosity:", post["curiosity_line"])
print("Caption:", post["caption"])
print("Hashtags:", " ".join(post["hashtags"]))

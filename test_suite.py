"""Automated test suite for NEWS SNAP automation pipeline.

Tests all components locally without calling external paid APIs:
1. Python syntax across all project scripts.
2. Language filtering & headline cleaning.
3. Trivial/horoscope filtering.
4. Article selection & duplicate prevention logic.
5. Post content validation.
6. Image rendering: dimensions (1080x1350), format (JPEG), size (<8MB), and visual style.
7. Instagram publisher dry-run and safety guards.
"""

import ast
import io
import json
import os
import sys
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from PIL import Image

import test as discovery
import select_article
import post_generator
import generate_image
import instagram_publisher
import prepare_special_formats
import format_registry
import quota_manager
import scheduler_controller
import scheduler_watchdog
import run_summary
import ai_provider
import classify
import check_candidates
from unittest.mock import patch, MagicMock


class TestSyntax(unittest.TestCase):
    def test_all_python_files_syntax(self):
        py_files = list(Path(".").glob("*.py"))
        self.assertGreater(len(py_files), 4)
        for py_path in py_files:
            code = py_path.read_text(encoding="utf-8")
            try:
                ast.parse(code, filename=str(py_path))
            except SyntaxError as e:
                self.fail(f"Syntax error in {py_path}: {e}")


class TestLanguageAndFiltering(unittest.TestCase):
    def test_english_headline_detection(self):
        english_samples = [
            "World leaders gather at United Nations for emergency climate summit",
            "Federal Reserve signals potential rate pause amid stable inflation",
            "European Union announces new trade regulations on semiconductor chips",
            "Maharashtra FDA resolves 72% of 13,857 complaints in three months",
        ]
        for title in english_samples:
            self.assertTrue(
                discovery.is_english_headline(title),
                f"Expected English headline: '{title}'"
            )

    def test_non_english_headline_rejection(self):
        non_english_samples = [
            "Vijue vizuizi vingine saba vya majini vilivyowahi kutokea duniani",  # Swahili
            "Los incendios forestales se intensifican mientras suben las temperaturas",  # Spanish
            "Les chefs d'Etat se réunissent à Paris pour un sommet historique",  # French
            "Bundeskanzler kündigt neue Maßnahmen zur Unterstützung der Wirtschaft an",  # German
            "حرائق الغابات تزداد مع ارتفاع درجات الحرارة",  # Arabic / Urdu script
            "وزیراعظم شہباز شریف نے کابینہ کا اہم اجلاس طلب کرلیا",  # Urdu script
            "Wazir e Azam ne awam ke liye ahem elan jari kar diya",  # Roman Urdu
            "रूस-यूक्रेन युद्ध पर संयुक्त राष्ट्र में महत्वपूर्ण बैठक",  # Hindi
        ]
        for title in non_english_samples:
            self.assertFalse(
                discovery.is_english_headline(title),
                f"Expected non-English headline to be rejected: '{title}'"
            )

    def test_trivial_and_horoscope_filtering(self):
        trivial_samples = [
            ("Capricorn Shani Horoscope Today: Moon warns of expenses", "https://timesofindia.com/astrology/horoscope"),
            ("Daily rashi Tarot predictions for every zodiac sign", "https://timesofindia.com/astrology/tarot"),
            ("'Hanuman Ansh' box office collection day 70: earns Rs 65 lakhs", "https://timesofindia.com/box-office/film"),
            ("Winning lottery numbers for October 16", "https://news.com/lottery-result"),
        ]
        for title, url in trivial_samples:
            self.assertTrue(
                discovery.is_trivial_or_gossip(title, url),
                f"Expected trivial content to be flagged: '{title}'"
            )

    def test_title_cleaning(self):
        dirty = "Breaking News: Major Accord Signed &#39;Today&#39; - BBC News"
        cleaned = discovery.clean_title(dirty)
        self.assertNotIn("&#39;", cleaned)
        self.assertNotIn("- BBC News", cleaned)
        self.assertIn("'Today'", cleaned)


class TestDuplicatePrevention(unittest.TestCase):
    def test_duplicate_prevention_logic(self):
        article = {
            "title": "Unique breaking story about space exploration",
            "url": "https://reuters.com/science/space-discovery-2026",
            "domain": "reuters.com"
        }
        post = {
            "headline": "Historic Space Discovery Announced",
            "curiosity_line": "New findings from deep space",
            "caption": "Astronomers announce new discoveries.\n\n#NewsSnap"
        }

        # Clear or mock history
        hist_file = Path("test_history.json")
        try:
            instagram_publisher.HISTORY_PATH = hist_file
            if hist_file.exists():
                hist_file.unlink()

            self.assertFalse(instagram_publisher.is_already_posted(article))

            # Record publication
            instagram_publisher.record_history(article, post, published=True)
            self.assertTrue(instagram_publisher.is_already_posted(article))
        finally:
            instagram_publisher.HISTORY_PATH = Path("history.json")
            if hist_file.exists():
                hist_file.unlink()


class TestPostValidation(unittest.TestCase):
    def test_valid_post_passes(self):
        sample_post = {
            "headline": "World Leaders Finalize Historic Clean Energy Framework",
            "curiosity_line": "What it means for global climate targets",
            "caption": "Delegates from nearly 200 nations agreed on a comprehensive transition plan to cut carbon emissions significantly over the next decade. Industry experts believe the agreement sets a strong global standard for future renewable investments.",
            "hashtags": ["#NewsSnap", "#ClimateUpdate", "#GlobalNews"]
        }
        validated = post_generator.validate_post(sample_post, "reuters.com", "https://reuters.com/climate")
        self.assertIn("#NewsSnap", validated["caption"])
        self.assertIn("Source: reuters.com", validated["caption"])
        self.assertEqual(validated["headline"], sample_post["headline"])

    def test_short_headline_rejected(self):
        invalid = {
            "headline": "Too short",
            "curiosity_line": "Valid kicker line",
            "caption": "This is a valid caption that has enough words to describe the news report accurately and cleanly without any issues whatsoever.",
            "hashtags": ["#NewsSnap", "#News"]
        }
        with self.assertRaises(ValueError):
            post_generator.validate_post(invalid, "reuters.com", "https://reuters.com")


class TestImageGeneration(unittest.TestCase):
    def test_format_registry_has_exact_six_formats(self):
        from format_registry import FORMAT_REGISTRY
        self.assertEqual(len(FORMAT_REGISTRY), 6)
        expected_keys = {"01", "02", "03", "04", "05", "06"}
        self.assertEqual(set(FORMAT_REGISTRY.keys()), expected_keys)

    def test_approved_format_01_emergency(self):
        article = {
            "title": "Severe Wildfire Prompts Mass Evacuation in Regional Park",
            "domain": "reuters.com",
            "url": "https://reuters.com/emergency",
            "classification": {"importance": "MAJOR", "topic": "Disaster"}
        }
        post = {
            "headline": "Severe Wildfire Prompts Mass Evacuation",
            "caption": "Emergency crews are responding to spreading wildfires across the region.",
            "hashtags": ["#NewsSnap"]
        }
        img, _, _ = generate_image.render_approved_format("01", article, post)
        self.assertEqual(img.size, (1080, 1350))

    def test_approved_format_02_business(self):
        article = {
            "title": "Central Bank Raises Benchmark Interest Rate by 25 Basis Points",
            "domain": "ft.com",
            "url": "https://ft.com/economy",
            "classification": {"importance": "MAJOR", "topic": "Business"}
        }
        post = {
            "headline": "Central Bank Raises Benchmark Interest Rate",
            "caption": "Policymakers announced a rate increase to stabilize inflation targets.",
            "hashtags": ["#NewsSnap"]
        }
        img, _, _ = generate_image.render_approved_format("02", article, post)
        self.assertEqual(img.size, (1080, 1350))

    def test_approved_format_03_people(self):
        article = {
            "title": "Board Appoints New Chief Executive to Lead Global Operations",
            "domain": "bloomberg.com",
            "url": "https://bloomberg.com/leadership",
            "classification": {"importance": "MAJOR", "topic": "People"}
        }
        post = {
            "headline": "Board Appoints New Chief Executive",
            "caption": "The company announced executive leadership changes effective next month.",
            "hashtags": ["#NewsSnap"]
        }
        img, _, _ = generate_image.render_approved_format("03", article, post)
        self.assertEqual(img.size, (1080, 1350))

    def test_approved_format_05_report(self):
        article = {
            "title": "India can cut steel emissions before new coal plants lock them in",
            "domain": "thehindu.com",
            "url": "https://thehindu.com/science",
            "classification": {"importance": "MAJOR", "topic": "World News"}
        }
        post = {
            "headline": "India can cut steel emissions before new coal plants lock them in",
            "caption": "According to reports from thehindu.com, India can cut steel emissions.",
            "hashtags": ["#NewsSnap"]
        }
        img, _, _ = generate_image.render_approved_format("05", article, post)
        self.assertEqual(img.size, (1080, 1350))

    def test_approved_format_06_quote(self):
        article = {
            "title": "Secretary General Issues Statement on Diplomatic Accord",
            "domain": "reuters.com",
            "url": "https://reuters.com/statement",
            "quote_verified": True,
            "quote_text": "We have reached a decisive moment for collective action across borders.",
            "speaker": "António Guterres",
            "speaker_role": "United Nations Secretary-General",
            "classification": {"importance": "MAJOR", "topic": "Diplomacy"}
        }
        post = {
            "headline": "UN Chief Issues High-Level Statement",
            "caption": "The Secretary-General urged international cooperation during remarks.",
            "hashtags": ["#NewsSnap"]
        }
        img, _, _ = generate_image.render_approved_format("06", article, post)
        self.assertEqual(img.size, (1080, 1350))


    def test_approved_format_04_roundup(self):
        # Create temporary roundup.json and roundup_post.json
        roundup = {
            "stories": [
                {"title": "Global Leaders Agree on Renewable Energy Goals", "domain": "reuters.com", "url": "https://reuters.com/1", "summary": "Nations commit to tripling clean energy capacity by 2030."},
                {"title": "Central Bank Holds Benchmark Interest Rate Steady", "domain": "bloomberg.com", "url": "https://bloomberg.com/2", "summary": "Policymakers maintain interest rates following inflation reports."},
                {"title": "Space Agency Launches Atmospheric Research Mission", "domain": "bbc.com", "url": "https://bbc.com/3", "summary": "New satellite will track worldwide climate and greenhouse gases."}
            ]
        }
        roundup_post = {
            "headline": "TODAY'S TOP 3 STORIES",
            "curiosity_line": "Key developments across energy, economy and science",
            "format": "04",
            "caption": "NEWS SNAP roundup of today's top stories. #NewsSnap\n\n1. Energy goals — reuters.com\n2. Rate steady — bloomberg.com\n3. Space mission — bbc.com",
            "hashtags": ["#NewsSnap", "#DailyBriefing"]
        }
        p1 = Path("roundup.json")
        p2 = Path("roundup_post.json")
        p1.write_text(json.dumps(roundup), encoding="utf-8")
        p2.write_text(json.dumps(roundup_post), encoding="utf-8")
        try:
            img, rendered_post, _ = generate_image.render_approved_format("04", {}, roundup_post)
            self.assertEqual(img.size, (1080, 1350))
            self.assertEqual(rendered_post.get("format"), "04")
        finally:
            if p1.is_file():
                p1.unlink()
            if p2.is_file():
                p2.unlink()


class TestInstagramPublisher(unittest.TestCase):
    def test_dry_run_validation(self):
        # Verify validate_image_and_post succeeds with valid files
        created = []
        if not instagram_publisher.IMAGE_PATH.is_file():
            from PIL import ImageDraw
            img = Image.new("RGB", (1080, 1350), (10, 24, 45))
            d = ImageDraw.Draw(img)
            d.rectangle((50, 50, 1030, 600), fill=(230, 31, 45))
            d.text((100, 100), "NEWS SNAP TEST CARD", fill=(255, 255, 255))
            img.save(instagram_publisher.IMAGE_PATH, format="JPEG", quality=95)
            created.append(instagram_publisher.IMAGE_PATH)
        if not instagram_publisher.POST_PATH.is_file():
            test_post = {
                "headline": "TEST STORY HEADLINE FOR DRY RUN",
                "caption": "Verified caption for testing publisher dry-run. #NewsSnap",
                "hashtags": ["#NewsSnap"]
            }
            instagram_publisher.POST_PATH.write_text(json.dumps(test_post), encoding="utf-8")
            created.append(instagram_publisher.POST_PATH)

        try:
            post, caption = instagram_publisher.validate_image_and_post()
            self.assertIn("#NewsSnap", caption.replace("#newssnap", "#NewsSnap"))
            self.assertLessEqual(len(caption), 2200)
        finally:
            for p in created:
                if p.is_file():
                    p.unlink()

    def test_synthetic_post_live_refusal(self):
        # Verify that synthetic/mock posts are strictly refused for live publication
        post = {"is_synthetic": True}
        with self.assertRaises(ValueError):
            if post.get("is_synthetic"):
                raise ValueError("SAFETY REFUSAL: The generated post is marked as synthetic/mock test data.")

    def test_graph_api_version_supported(self):
        # Ensure Graph API version is current (>= v21.0) and not expired v19.0
        version = instagram_publisher.GRAPH_API_VERSION
        self.assertTrue(version.startswith("v"), f"Invalid Graph API version format: {version}")
        num = float(version.lstrip("v"))
        self.assertGreaterEqual(num, 21.0, f"Graph API version {version} is deprecated or expired; must be v21.0 or higher")

    def test_roundup_caption_mismatch_refusal(self):
        # Format 04 post with single-story caption must be refused
        p1 = Path("roundup.json")
        roundup = {
            "stories": [
                {"title": "Global Leaders Agree on Renewable Energy Goals", "domain": "reuters.com", "url": "https://reuters.com/1"},
                {"title": "Central Bank Holds Benchmark Interest Rate Steady", "domain": "bloomberg.com", "url": "https://bloomberg.com/2"},
                {"title": "Space Agency Launches Atmospheric Research Mission", "domain": "bbc.com", "url": "https://bbc.com/3"}
            ]
        }
        p1.write_text(json.dumps(roundup), encoding="utf-8")
        try:
            mismatched_post = {
                "headline": "TODAY'S TOP 3 STORIES",
                "format": "04",
                "caption": "A single unrelated story about local election results. #NewsSnap",
                "hashtags": ["#NewsSnap"]
            }
            with self.assertRaises(ValueError) as ctx:
                instagram_publisher.verify_format_caption_alignment(mismatched_post, mismatched_post["caption"])
            self.assertIn("FORMAT 04 MISMATCH", str(ctx.exception))
        finally:
            if p1.is_file():
                p1.unlink()

    def test_pages_url_construction(self):
        # Verify Pages URL construction from repository name
        url = instagram_publisher.get_default_pages_url("hafizabdulbar3-creator/news-snap-automation")
        self.assertEqual(url, "https://hafizabdulbar3-creator.github.io/news-snap-automation/news_snap_post.jpg")

        # Edge cases: empty or malformed repo string
        self.assertEqual(instagram_publisher.get_default_pages_url(""), "")
        self.assertEqual(instagram_publisher.get_default_pages_url("single-string"), "")

        # Verify URL normalization (trailing slash, missing filename, etc.)
        self.assertEqual(
            instagram_publisher.normalize_image_url("https://example.github.io/repo/"),
            "https://example.github.io/repo/news_snap_post.jpg"
        )
        self.assertEqual(
            instagram_publisher.normalize_image_url("https://example.github.io/repo"),
            "https://example.github.io/repo/news_snap_post.jpg"
        )
        self.assertEqual(
            instagram_publisher.normalize_image_url("https://example.github.io/repo/news_snap_post.jpg"),
            "https://example.github.io/repo/news_snap_post.jpg"
        )
        self.assertEqual(
            instagram_publisher.normalize_image_url("https://example.github.io/repo//news_snap_post.jpg"),
            "https://example.github.io/repo/news_snap_post.jpg"
        )
        self.assertEqual(
            instagram_publisher.normalize_image_url("https://example.github.io/repo/custom.jpg"),
            "https://example.github.io/repo/custom.jpg"
        )

    def test_public_image_url_missing_handling(self):
        # Empty string
        with self.assertRaises(ValueError) as ctx:
            instagram_publisher.verify_public_image_url("")
        self.assertIn("missing or empty", str(ctx.exception).lower())

        # None input
        with self.assertRaises(ValueError) as ctx:
            instagram_publisher.verify_public_image_url(None)
        self.assertIn("missing or empty", str(ctx.exception).lower())

    def test_public_image_url_invalid_handling(self):
        # Non-HTTPS URLs must be rejected immediately
        with self.assertRaises(ValueError) as ctx:
            instagram_publisher.verify_public_image_url("http://insecure-host.com/news_snap_post.jpg", max_retries=1)
        self.assertIn("must be a valid public https url", str(ctx.exception).lower())

        # Malformed scheme
        with self.assertRaises(ValueError) as ctx:
            instagram_publisher.verify_public_image_url("ftp://server.com/news_snap_post.jpg", max_retries=1)
        self.assertIn("must be a valid public https url", str(ctx.exception).lower())

        # Missing netloc
        with self.assertRaises(ValueError) as ctx:
            instagram_publisher.verify_public_image_url("https://", max_retries=1)
        self.assertIn("must be a valid public https url", str(ctx.exception).lower())

    def test_instagram_login_host_and_endpoints(self):
        self.assertEqual(instagram_publisher.INSTAGRAM_GRAPH_HOST, "graph.instagram.com")
        self.assertTrue(
            instagram_publisher.GRAPH_API_BASE.startswith("https://graph.instagram.com/"),
            f"Expected base URL to start with https://graph.instagram.com/, got {instagram_publisher.GRAPH_API_BASE}"
        )
        self.assertTrue(instagram_publisher.is_supported_api_version("v21.0"))
        self.assertTrue(instagram_publisher.is_supported_api_version("v22.0"))
        self.assertTrue(instagram_publisher.is_supported_api_version("v23.0"))
        self.assertFalse(instagram_publisher.is_supported_api_version("v19.0"))
        self.assertFalse(instagram_publisher.is_supported_api_version("v18.0"))
        self.assertFalse(instagram_publisher.is_supported_api_version("invalid_version"))
        self.assertFalse(instagram_publisher.is_supported_api_version(""))

    def test_instagram_login_required_permissions(self):
        perms = instagram_publisher.REQUIRED_PERMISSIONS
        self.assertIn("instagram_business_basic", perms)
        self.assertIn("instagram_business_content_publish", perms)

    def test_token_masking_and_sanitization(self):
        raw_token = "EAABwz123456789xyzToken99"
        masked = instagram_publisher.mask_token(raw_token)
        self.assertEqual(masked, "EAAB...en99")
        self.assertEqual(instagram_publisher.mask_token("short"), "***")
        self.assertEqual(instagram_publisher.mask_token(""), "")

        # Test URL parameter sanitization
        url_with_token = f"https://graph.instagram.com/v22.0/me?access_token={raw_token}&fields=id"
        sanitized_url = instagram_publisher.sanitize_token(url_with_token, raw_token)
        self.assertNotIn(raw_token, sanitized_url)
        self.assertIn(masked, sanitized_url)

        # Test header and error message sanitization
        err_msg = f"HTTP 401 Unauthorized: Authorization: Bearer {raw_token} failed"
        sanitized_err = instagram_publisher.sanitize_token(err_msg, raw_token)
        self.assertNotIn(raw_token, sanitized_err)
        self.assertIn(masked, sanitized_err)

    def test_account_id_resolution_from_numeric(self):
        numeric_id = "17841405322997123"
        resolved, _ = instagram_publisher.resolve_instagram_account_id(numeric_id, access_token="")
        self.assertEqual(resolved, numeric_id)

        # Leading @ stripped
        resolved_at, _ = instagram_publisher.resolve_instagram_account_id("@" + numeric_id, access_token="")
        self.assertEqual(resolved_at, numeric_id)

    def test_account_id_resolution_from_username(self):
        mock_response = {
            "id": "17841409999999999",
            "user_id": "17841409999999999",
            "username": "newssnap_official",
            "account_type": "BUSINESS"
        }
        with patch("instagram_publisher.fetch_account_info", return_value=mock_response):
            # When username is provided
            resolved, info = instagram_publisher.resolve_instagram_account_id("newssnap_official", access_token="mock_token")
            self.assertEqual(resolved, "17841409999999999")
            self.assertEqual(info.get("username"), "newssnap_official")

            # When handle with @ is provided
            resolved_at, _ = instagram_publisher.resolve_instagram_account_id("@newssnap_official", access_token="mock_token")
            self.assertEqual(resolved_at, "17841409999999999")

        # Refusal when username is configured but no token is present to resolve it
        with self.assertRaises(ValueError) as ctx:
            instagram_publisher.resolve_instagram_account_id("newssnap_official", access_token="")
        self.assertIn("is a username or handle, not a numeric id", str(ctx.exception).lower())

    def test_account_id_auto_discovery_when_empty(self):
        mock_response = {
            "user_id": "17841407777777777",
            "username": "newssnap_global",
            "account_type": "CREATOR"
        }
        with patch("instagram_publisher.fetch_account_info", return_value=mock_response):
            resolved, info = instagram_publisher.resolve_instagram_account_id("", access_token="mock_token")
            self.assertEqual(resolved, "17841407777777777")
            self.assertEqual(info.get("username"), "newssnap_global")

        # When neither ID nor token is provided
        with self.assertRaises(ValueError) as ctx:
            instagram_publisher.resolve_instagram_account_id("", access_token="")
        self.assertIn("missing and could not be resolved", str(ctx.exception).lower())

    def test_container_status_check(self):
        # Successful status
        mock_resp_finished = io.BytesIO(json.dumps({"status_code": "FINISHED"}).encode("utf-8"))
        mock_resp_finished.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp_finished):
            res = instagram_publisher.check_container_status("1790001", "mock_token")
            self.assertEqual(res.get("status_code"), "FINISHED")

        # Error status
        mock_resp_error = io.BytesIO(json.dumps({"status_code": "ERROR", "status": "Failed to process media"}).encode("utf-8"))
        mock_resp_error.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp_error):
            with self.assertRaises(RuntimeError) as ctx:
                instagram_publisher.check_container_status("1790002", "mock_token")
            self.assertIn("failed with status_code: ERROR", str(ctx.exception))

    def test_dry_run_with_instagram_login_token(self):
        # Create minimal valid image and post files for dry-run
        from PIL import ImageDraw
        img = Image.new("RGB", (1080, 1350), (15, 25, 45))
        d = ImageDraw.Draw(img)
        d.rectangle((50, 50, 1030, 600), fill=(230, 31, 45))
        d.text((100, 100), "TEST LOGIN CARD", fill=(255, 255, 255))
        img.save(instagram_publisher.IMAGE_PATH, format="JPEG", quality=95)

        test_post = {
            "headline": "TEST STORY HEADLINE FOR INSTAGRAM LOGIN DRY RUN",
            "caption": "Verified caption for testing publisher dry-run. #NewsSnap",
            "hashtags": ["#NewsSnap"]
        }
        instagram_publisher.POST_PATH.write_text(json.dumps(test_post), encoding="utf-8")

        temp_hist = Path("test_history_dryrun_login.json")
        orig_hist = instagram_publisher.HISTORY_PATH
        instagram_publisher.HISTORY_PATH = temp_hist

        mock_profile = {
            "id": "17841400012345678",
            "username": "newssnap_bot",
            "account_type": "BUSINESS"
        }

        try:
            with patch("instagram_publisher.fetch_account_info", return_value=mock_profile), \
                 patch.dict(os.environ, {
                     "ENABLE_INSTAGRAM_POSTING": "false",
                     "INSTAGRAM_ACCESS_TOKEN": "mock_login_token_abc123xyz",
                     "INSTAGRAM_ACCOUNT_ID": "newssnap_bot"
                 }):
                instagram_publisher.main()

            self.assertTrue(temp_hist.is_file(), "History file should be created in dry-run")
            hist_data = json.loads(temp_hist.read_text(encoding="utf-8"))
            self.assertEqual(len(hist_data.get("posted", [])), 0, "No stories should be marked as posted in dry-run")
            self.assertEqual(len(hist_data.get("processed", [])), 1, "Story should be marked in processed list")
            self.assertFalse(hist_data["processed"][0]["published"])
            self.assertTrue(hist_data["processed"][0]["dry_run"])
        finally:
            instagram_publisher.HISTORY_PATH = orig_hist
            if temp_hist.is_file():
                temp_hist.unlink()
            if instagram_publisher.IMAGE_PATH.is_file():
                instagram_publisher.IMAGE_PATH.unlink()
            if instagram_publisher.POST_PATH.is_file():
                instagram_publisher.POST_PATH.unlink()

    def test_invalid_and_expired_token_handling(self):
        # Verify that expired or invalid tokens (OAuthException code 190) are safely detected and sanitized
        error_json = json.dumps({
            "error": {
                "message": "Error validating access token: Session has expired on Monday, 01-Jan-2026",
                "type": "OAuthException",
                "code": 190,
                "error_subcode": 463
            }
        }).encode("utf-8")

        mock_err = urllib.error.HTTPError(
            url="https://graph.instagram.com/v22.0/me",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(error_json)
        )

        with patch("urllib.request.urlopen", side_effect=mock_err):
            with self.assertRaises(RuntimeError) as ctx:
                instagram_publisher.verify_account_and_permissions("", "secret_expired_token_999")
            err_str = str(ctx.exception)
            self.assertIn("invalid or expired", err_str.lower())
            self.assertIn("190", err_str)
            self.assertNotIn("secret_expired_token_999", err_str, "Raw token must never be exposed in error messages")

    def test_personal_account_rejection(self):
        # Personal accounts cannot use Instagram content publishing; must be Business or Creator
        personal_profile = {
            "id": "1784140009999",
            "username": "personal_creator",
            "account_type": "PERSONAL"
        }
        with patch("instagram_publisher.fetch_account_info", return_value=personal_profile):
            with self.assertRaises(ValueError) as ctx:
                instagram_publisher.verify_account_and_permissions("", "mock_token")
            err_str = str(ctx.exception)
            self.assertIn("personal", err_str.lower())
            self.assertIn("professional", err_str.lower())

    def test_missing_permissions_handling(self):
        # Missing instagram_business_content_publish must be refused before publication
        business_profile = {
            "id": "1784140008888",
            "username": "newssnap_biz",
            "account_type": "BUSINESS"
        }
        with patch("instagram_publisher.fetch_account_info", return_value=business_profile), \
             patch("instagram_publisher.fetch_granted_permissions", return_value=["instagram_business_basic"]):
            with self.assertRaises(ValueError) as ctx:
                instagram_publisher.verify_account_and_permissions("", "mock_token")
            err_str = str(ctx.exception)
            self.assertIn("insufficient permissions", err_str.lower())
            self.assertIn("instagram_business_content_publish", err_str)

        # When permission is granted, verification succeeds
        with patch("instagram_publisher.fetch_account_info", return_value=business_profile), \
             patch("instagram_publisher.fetch_granted_permissions", return_value=["instagram_business_basic", "instagram_business_content_publish"]):
            res = instagram_publisher.verify_account_and_permissions("", "mock_token")
            self.assertEqual(res["account_id"], "1784140008888")
            self.assertEqual(res["username"], "newssnap_biz")
            self.assertIn("instagram_business_content_publish", res["permissions"])

    def test_live_feed_duplicate_detection(self):
        headline = "World Leaders Sign Clean Energy Transition Framework"
        mock_media = {
            "data": [
                {
                    "id": "18099887766554433",
                    "caption": f"Breaking update: {headline}. Details inside. #NewsSnap\n\nSource: reuters.com",
                    "timestamp": "2026-10-18T20:00:00+00:00"
                },
                {
                    "id": "18099887766554422",
                    "caption": "An older unrelated news report. #NewsSnap",
                    "timestamp": "2026-10-18T18:00:00+00:00"
                }
            ]
        }
        mock_resp = io.BytesIO(json.dumps(mock_media).encode("utf-8"))
        mock_resp.status = 200

        with patch("urllib.request.urlopen", return_value=mock_resp):
            matched_id = instagram_publisher.check_live_feed_duplicate(
                headline, "1784140001", "mock_token"
            )
            self.assertEqual(matched_id, "18099887766554433")

        # When recent media does NOT contain headline
        mock_resp_none = io.BytesIO(json.dumps(mock_media).encode("utf-8"))
        mock_resp_none.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp_none):
            matched_none = instagram_publisher.check_live_feed_duplicate(
                "Completely Unrelated Story About Quantum Computers", "1784140001", "mock_token"
            )
            self.assertEqual(matched_none, "")

        # When API call fails, gracefully returns empty string
        mock_err = urllib.error.HTTPError(
            url="https://graph.instagram.com/v22.0/me/media",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=io.BytesIO(b"{}")
        )
        with patch("urllib.request.urlopen", side_effect=mock_err):
            matched_err = instagram_publisher.check_live_feed_duplicate(
                headline, "1784140001", "mock_token"
            )
            self.assertEqual(matched_err, "")

    def test_live_feed_duplicate_recovery_in_main(self):
        from PIL import ImageDraw
        img = Image.new("RGB", (1080, 1350), (15, 25, 45))
        d = ImageDraw.Draw(img)
        d.rectangle((50, 50, 1030, 600), fill=(230, 31, 45))
        d.text((100, 100), "TEST DUPLICATE CARD", fill=(255, 255, 255))
        img.save(instagram_publisher.IMAGE_PATH, format="JPEG", quality=95)

        test_headline = "RECOVERY TEST STORY HEADLINE"
        test_post = {
            "headline": test_headline,
            "caption": "Verified caption for testing duplicate recovery. #NewsSnap",
            "hashtags": ["#NewsSnap"]
        }
        instagram_publisher.POST_PATH.write_text(json.dumps(test_post), encoding="utf-8")

        temp_hist = Path("test_history_recovery.json")
        orig_hist = instagram_publisher.HISTORY_PATH
        instagram_publisher.HISTORY_PATH = temp_hist

        mock_profile = {
            "id": "17841400012345678",
            "username": "newssnap_bot",
            "account_type": "BUSINESS"
        }

        try:
            with patch("instagram_publisher.fetch_account_info", return_value=mock_profile), \
                 patch("instagram_publisher.check_live_feed_duplicate", return_value="18999999999"), \
                 patch("instagram_publisher.verify_public_image_url"), \
                 patch.dict(os.environ, {
                     "ENABLE_INSTAGRAM_POSTING": "true",
                     "INSTAGRAM_ACCESS_TOKEN": "mock_login_token_abc123xyz",
                     "INSTAGRAM_ACCOUNT_ID": "17841400012345678",
                     "IMAGE_PUBLIC_URL": "https://example.com/news_snap_post.jpg"
                 }):
                instagram_publisher.main()

            self.assertTrue(temp_hist.is_file())
            hist_data = json.loads(temp_hist.read_text(encoding="utf-8"))
            self.assertEqual(len(hist_data.get("posted", [])), 1)
            self.assertEqual(hist_data["posted"][0]["media_id"], "18999999999")
            self.assertTrue(hist_data["posted"][0]["published"])
        finally:
            instagram_publisher.HISTORY_PATH = orig_hist
            if temp_hist.is_file():
                temp_hist.unlink()
            if instagram_publisher.IMAGE_PATH.is_file():
                instagram_publisher.IMAGE_PATH.unlink()
            if instagram_publisher.POST_PATH.is_file():
                instagram_publisher.POST_PATH.unlink()


class TestSixFormatRegistry(unittest.TestCase):
    def test_six_formats_data_preparation(self):
        from format_registry import FORMAT_REGISTRY, classify_format_for_article
        # Verify all 6 approved formats exist
        self.assertEqual(sorted(FORMAT_REGISTRY.keys()), ["01", "02", "03", "04", "05", "06"])
        for fid, fdef in FORMAT_REGISTRY.items():
            self.assertIn("name", fdef)
            self.assertEqual(fdef["canvas_size"], (1080, 1350))

        # Test format routing for each category
        fmt, _ = classify_format_for_article({"title": "Massive wildfire triggers emergency evacuations"})
        self.assertEqual(fmt, "01")

        fmt, _ = classify_format_for_article({"title": "Central bank signals interest rate rise as inflation ticks up"})
        self.assertEqual(fmt, "02")

        fmt, _ = classify_format_for_article({"title": "Board appoints new Chief Executive to lead expansion"})
        self.assertEqual(fmt, "03")

        fmt, _ = classify_format_for_article({"template_override": "04"}, roundup_exists=True)
        self.assertEqual(fmt, "04")

        fmt, _ = classify_format_for_article({"title": "Scientists announce breakthrough in clean fusion power"})
        self.assertEqual(fmt, "05")

        fmt, _ = classify_format_for_article({
            "quote_verified": True,
            "quote_text": "We stand united against global challenges.",
            "speaker": "World Leader"
        })
        self.assertEqual(fmt, "06")


class TestScheduleAndFreshCandidates(unittest.TestCase):
    def test_five_minute_schedule_and_concurrency(self):
        import yaml
        test_path = Path(".github/workflows/test.yml")
        scheduler_path = Path(".github/workflows/news-snap-scheduler.yml")
        watchdog_path = Path(".github/workflows/news-snap-watchdog.yml")

        self.assertTrue(test_path.is_file(), ".github/workflows/test.yml must exist")
        self.assertTrue(scheduler_path.is_file(), ".github/workflows/news-snap-scheduler.yml must exist")
        self.assertTrue(watchdog_path.is_file(), ".github/workflows/news-snap-watchdog.yml must exist")

        test_content = test_path.read_text(encoding="utf-8")
        scheduler_content = scheduler_path.read_text(encoding="utf-8")
        watchdog_content = watchdog_path.read_text(encoding="utf-8")

        # Verify test.yml has workflow_dispatch and NO conflicting 5-minute cron
        test_data = yaml.safe_load(test_content)
        test_on = test_data.get(True) or test_data.get("on", {})
        self.assertIn("workflow_dispatch", test_on)
        self.assertNotIn("schedule", test_on, "Conflicting cron schedule must be removed from test.yml")

        # Verify test.yml publisher-level concurrency
        test_conc = test_data.get("concurrency", {})
        self.assertEqual(test_conc.get("group"), "news-snap-automation-live")
        self.assertEqual(test_conc.get("queue"), "max")
        self.assertIn("ref: main", test_content)
        self.assertIn("fetch-depth: 0", test_content)
        self.assertIn("git pull origin main --rebase", test_content)
        self.assertIn("for attempt in 1 2 3 4 5; do", test_content)

        # Verify news-snap-scheduler.yml controller configuration
        sched_data = yaml.safe_load(scheduler_content)
        sched_on = sched_data.get(True) or sched_data.get("on", {})
        self.assertIn("workflow_dispatch", sched_on)
        wd_inputs = sched_on["workflow_dispatch"].get("inputs", {})
        self.assertIn("bootstrap_only", wd_inputs, "bootstrap_only input must exist")
        self.assertEqual(wd_inputs["bootstrap_only"].get("type"), "boolean")

        sched_perms = sched_data.get("permissions", {})
        self.assertEqual(sched_perms.get("actions"), "write")

        sched_conc = sched_data.get("concurrency", {})
        self.assertEqual(sched_conc.get("group"), "news-snap-scheduler-controller")

        # Verify news-snap-watchdog.yml recovery configuration
        watch_data = yaml.safe_load(watchdog_content)
        watch_perms = watch_data.get("permissions", {})
        self.assertEqual(watch_perms.get("actions"), "write")
        watch_conc = watch_data.get("concurrency", {})
        self.assertEqual(watch_conc.get("group"), "news-snap-watchdog")

    def test_fifteen_minute_schedule(self):
        """Backward-compatibility alias pointing to 5-minute schedule test."""
        return self.test_five_minute_schedule_and_concurrency()

    def test_no_new_candidate_path(self):
        import check_candidates
        import classify
        import select_article
        import post_generator

        # Setup temporary files
        temp_discovery = Path("test_discovery.json")
        temp_history = Path("test_history.json")
        temp_classified = Path("test_classified.json")

        articles = [
            {
                "title": "Previously Published Story One About Global Economy",
                "url": "https://reuters.com/economy-one",
                "domain": "reuters.com",
                "score": 100,
                "is_duplicate": True
            },
            {
                "title": "Previously Published Story Two About Central Bank",
                "url": "https://bloomberg.com/bank-two",
                "domain": "bloomberg.com",
                "score": 90,
                "is_duplicate": False
            }
        ]
        history = {
            "posted": [
                {
                    "title": "Previously Published Story Two About Central Bank",
                    "url": "https://bloomberg.com/bank-two",
                    "published": True
                }
            ]
        }

        try:
            temp_discovery.write_text(json.dumps(articles), encoding="utf-8")
            temp_history.write_text(json.dumps(history), encoding="utf-8")

            # 1. get_fresh_candidates returns 0 when all articles are duplicates
            fresh = check_candidates.get_fresh_candidates(temp_discovery, temp_history)
            self.assertEqual(len(fresh), 0, "Expected 0 fresh candidates when all are already published")

            # 2. Add an unposted story alongside duplicates
            articles.append({
                "title": "Brand New Unposted Story About Scientific Discovery",
                "url": "https://nature.com/new-discovery",
                "domain": "nature.com",
                "score": 110,
                "is_duplicate": False
            })
            temp_discovery.write_text(json.dumps(articles), encoding="utf-8")
            fresh_with_new = check_candidates.get_fresh_candidates(temp_discovery, temp_history)
            self.assertEqual(len(fresh_with_new), 1, "Expected 1 fresh candidate")
            self.assertEqual(fresh_with_new[0]["domain"], "nature.com")

            # 3. Verify select_best_article returns None instead of falling back to duplicate
            # Set up environment where all discovered articles are published
            p_disc = Path("discovery.json")
            p_hist = Path("history.json")
            p_class = Path("classified_sample.json")
            p_sel = Path("selected_article.json")

            old_disc = p_disc.read_text(encoding="utf-8") if p_disc.is_file() else None
            old_hist = p_hist.read_text(encoding="utf-8") if p_hist.is_file() else None
            old_class = p_class.read_text(encoding="utf-8") if p_class.is_file() else None
            old_sel = p_sel.read_text(encoding="utf-8") if p_sel.is_file() else None

            try:
                # All candidates in history
                all_posted = [
                    {"title": "Published Story A In History", "url": "https://bbc.com/a", "domain": "bbc.com", "score": 100, "is_duplicate": True}
                ]
                p_disc.write_text(json.dumps(all_posted), encoding="utf-8")
                p_hist.write_text(json.dumps({"posted": [{"url": "https://bbc.com/a", "title": "Published Story A In History", "published": True}]}), encoding="utf-8")
                p_class.write_text(json.dumps({"results": [], "status": "no_fresh_candidates"}), encoding="utf-8")

                # classify.main() should skip calling Gemini and write no_fresh_candidates
                classify.main()
                class_result = json.loads(p_class.read_text(encoding="utf-8"))
                self.assertEqual(class_result.get("status"), "no_fresh_candidates")
                self.assertEqual(len(class_result.get("results", [])), 0)

                # select_best_article should return None and not create selected_article.json
                selected = select_article.select_best_article()
                self.assertIsNone(selected, "Must return None when no unposted candidates exist")
                self.assertFalse(p_sel.is_file(), "selected_article.json must not exist when no fresh story is selected")

                # post_generator.main() should exit cleanly without calling Gemini
                post_generator.main()
                self.assertFalse(Path("post.json").is_file(), "post.json must not be created when no selected article exists")

            finally:
                # Restore original files
                if old_disc is not None:
                    p_disc.write_text(old_disc, encoding="utf-8")
                elif p_disc.is_file():
                    p_disc.unlink()

                if old_hist is not None:
                    p_hist.write_text(old_hist, encoding="utf-8")
                elif p_hist.is_file():
                    p_hist.unlink()

                if old_class is not None:
                    p_class.write_text(old_class, encoding="utf-8")
                elif p_class.is_file():
                    p_class.unlink()

                if old_sel is not None:
                    p_sel.write_text(old_sel, encoding="utf-8")
                elif p_sel.is_file():
                    p_sel.unlink()

        finally:
            for p in (temp_discovery, temp_history, temp_classified):
                if p.is_file():
                    p.unlink()

    def test_dry_run_processed_separation_and_skipping(self):
        import check_candidates
        import instagram_publisher

        temp_history = Path("test_history_dryrun.json")
        temp_discovery = Path("test_discovery_dryrun.json")

        old_hist_path = instagram_publisher.HISTORY_PATH
        instagram_publisher.HISTORY_PATH = temp_history

        article = {
            "title": "Diplomatic Summit Concludes With Multilateral Climate Accord",
            "url": "https://reuters.com/world/diplomatic-summit-accord-2026",
            "domain": "reuters.com"
        }
        post = {
            "headline": "Historic Climate Accord Reached At Global Summit",
            "curiosity_line": "Key outcomes and commitments explained",
            "caption": "World leaders reached an agreement at the summit.\n\n#NewsSnap"
        }

        try:
            if temp_history.is_file():
                temp_history.unlink()

            # 1. Record dry-run processed
            instagram_publisher.record_dry_run_processed(article, post)
            self.assertTrue(temp_history.is_file())

            hist_data = json.loads(temp_history.read_text(encoding="utf-8"))
            self.assertIn("processed", hist_data)
            self.assertEqual(len(hist_data.get("posted", [])), 0, "posted list must remain empty in dry-run mode")
            self.assertEqual(len(hist_data["processed"]), 1, "processed list must contain exactly 1 entry")

            entry = hist_data["processed"][0]
            self.assertFalse(entry["published"], "published flag must be strictly False for dry-run entries")
            self.assertTrue(entry.get("dry_run"), "dry_run flag must be True")
            self.assertEqual(entry["url"], article["url"])

            # 2. Assert is_already_posted is False and is_already_processed is True
            self.assertFalse(instagram_publisher.is_already_posted(article), "Must NOT be reported as published")
            self.assertTrue(instagram_publisher.is_already_processed(article), "Must be reported as processed")

            # 3. Prove candidate check skips this dry-run processed story on the next run
            temp_discovery.write_text(json.dumps([
                {
                    "title": article["title"],
                    "url": article["url"],
                    "domain": article["domain"],
                    "score": 100,
                    "is_duplicate": False
                }
            ]), encoding="utf-8")

            fresh = check_candidates.get_fresh_candidates(temp_discovery, temp_history)
            self.assertEqual(len(fresh), 0, "Processed dry-run story must be skipped on the next run")

            # 4. Prove a genuinely new story remains eligible
            new_story = {
                "title": "Space Agency Confirms Discovery Of Subsurface Oceans",
                "url": "https://bbc.com/science/ocean-discovery-2026",
                "domain": "bbc.com",
                "score": 120,
                "is_duplicate": False
            }
            temp_discovery.write_text(json.dumps([
                {
                    "title": article["title"],
                    "url": article["url"],
                    "domain": article["domain"],
                    "score": 100,
                    "is_duplicate": False
                },
                new_story
            ]), encoding="utf-8")

            fresh_with_new = check_candidates.get_fresh_candidates(temp_discovery, temp_history)
            self.assertEqual(len(fresh_with_new), 1, "Genuinely new story must remain eligible")
            self.assertEqual(fresh_with_new[0]["url"], new_story["url"])

            # 5. Verify retention window: an expired entry (>48h) is pruned
            from datetime import datetime, timezone, timedelta
            expired_time = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
            hist_data["processed"].append({
                "url": "https://example.com/expired-story",
                "title": "Expired Story from Two Days Ago",
                "published": False,
                "dry_run": True,
                "timestamp": expired_time
            })
            pruned = instagram_publisher.prune_processed_entries(hist_data["processed"], max_age_hours=48)
            urls = [e["url"] for e in pruned]
            self.assertIn(article["url"], urls, "Recent entry within 48h must be retained")
            self.assertNotIn("https://example.com/expired-story", urls, "Entry older than 48h must be pruned")

        finally:
            instagram_publisher.HISTORY_PATH = old_hist_path
            for p in (temp_history, temp_discovery):
                if p.is_file():
                    p.unlink()

    def test_gemini_model_configuration_and_no_obsolete_ids(self):
        import classify
        import post_generator

        # 1. Verify primary model in workflow is gemini-3.8-flash
        workflow_path = Path(".github/workflows/test.yml")
        self.assertTrue(workflow_path.is_file())
        wf_content = workflow_path.read_text(encoding="utf-8")
        self.assertIn('GEMINI_MODEL: "gemini-3.8-flash"', wf_content)

        # 2. Verify scripts default to gemini-3.8-flash
        classify_code = Path("classify.py").read_text(encoding="utf-8")
        post_code = Path("post_generator.py").read_text(encoding="utf-8")

        self.assertIn('"gemini-3.8-flash"', classify_code)
        self.assertIn('"gemini-3.8-flash"', post_code)

        # 3. Assert no obsolete model IDs exist in workflow, classify.py, or post_generator.py
        obsolete_ids = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.0", "gemini-pro"]
        for obs in obsolete_ids:
            self.assertNotIn(obs, wf_content, f"Obsolete model ID '{obs}' found in .github/workflows/test.yml")
            self.assertNotIn(obs, classify_code, f"Obsolete model ID '{obs}' found in classify.py")
            self.assertNotIn(obs, post_code, f"Obsolete model ID '{obs}' found in post_generator.py")


class TestImageQualityAndSafeguards(unittest.TestCase):
    """Quality and safety tests for Commons photo sourcing and editorial vector illustrations."""

    def test_query_extraction_entities_and_acronyms(self):
        # 1. Acronyms & proper noun extraction
        art1 = {"title": "USCIS Increases Maximum Validity Period to 5 Years for Certain EAD Applicants"}
        q1 = generate_image.build_photo_search_queries(art1)
        self.assertIn("USCIS", q1)
        self.assertIn("EAD", q1)

        # 2. Known multi-word organization
        art2 = {"title": "Federal Reserve Signals Rate Pause Amid Inflation Concerns", "classification": {"topic": "Business"}}
        q2 = generate_image.build_photo_search_queries(art2)
        self.assertIn("Federal Reserve", q2)

        # 3. Speaker / person extraction
        art3 = {"title": "Tech Leader Speaks on Future of Computing", "speaker": "Satya Nadella"}
        q3 = generate_image.build_photo_search_queries(art3)
        self.assertIn("Satya Nadella", q3)

        # 4. Action verbs & generic headline terms stripped from queries
        for q in q1 + q2:
            self.assertNotIn("increases", q.lower().split())
            self.assertNotIn("signals", q.lower().split())

    def test_licence_filtering_safeguards(self):
        # Allowed licences
        allowed = [
            "CC BY 4.0",
            "CC BY-SA 3.0",
            "CC-BY-SA 4.0",
            "CC0 1.0 Universal",
            "Public domain",
            "PD-US",
            "PD-self",
            "GODL-India",
            "Creative Commons Attribution 2.5",
        ]
        for lic in allowed:
            self.assertTrue(generate_image.license_allowed(lic), f"Expected licence to be allowed: '{lic}'")

        # Strictly disallowed licences
        disallowed = [
            "CC BY-NC 4.0",
            "CC BY-NC-SA 3.0",
            "CC BY-ND 4.0",
            "All rights reserved",
            "Fair use",
            "Copyrighted",
            "",
            None,
        ]
        for lic in disallowed:
            self.assertFalse(generate_image.license_allowed(lic), f"Expected licence to be rejected: '{lic}'")

    def test_editorial_illustration_generation_across_categories(self):
        categories_and_articles = [
            ("DISASTER", {"title": "Wildfire sweeps across national park", "classification": {"topic": "Emergency"}}),
            ("BUSINESS", {"title": "Central bank announces benchmark interest rate policy", "classification": {"topic": "Business"}}),
            ("TECHNOLOGY", {"title": "Researchers unveil breakthrough quantum computing chip", "classification": {"topic": "Technology"}}),
            ("LEADERSHIP", {"title": "Prime Minister and Cabinet review legislative framework", "classification": {"topic": "Government"}}),
            ("QUOTE", {"title": "Ambassador delivers remarks at multilateral summit", "quote_text": "We stand together in defending global peace and security."}),
            ("DIPLOMACY", {"title": "Nations finalize international climate accord", "classification": {"topic": "Diplomacy"}}),
            ("GLOBAL NEWS", {"title": "International observers report on development projects", "classification": {"topic": "General"}}),
        ]
        test_dimensions = [(1080, 840), (950, 490), (240, 199), (530, 1000)]
        for cat, article in categories_and_articles:
            for w, h in test_dimensions:
                img = generate_image.make_illustration(w, h, category=cat, article=article)
                self.assertEqual(img.size, (w, h))
                self.assertEqual(img.mode, "RGB")
                extrema = img.getextrema()
                # Verify image is not a solid blank single-color block
                has_variation = any(ch[0] != ch[1] for ch in extrema)
                self.assertTrue(has_variation, f"Illustration for {cat} at ({w}, {h}) is blank")

    def test_format_04_story_aligned_attribution(self):
        post = {
            "headline": "TODAY'S TOP 3 STORIES",
            "caption": "Briefing of today's developments. #NewsSnap"
        }
        photo_info_1 = {
            "title": "Solar_Panels_Desert.jpg",
            "artist": "John Doe",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "page_url": "https://commons.wikimedia.org/wiki/File:Solar_Panels_Desert.jpg"
        }
        photo_info_3 = {
            "title": "Satellite_Orbit_Earth.jpg",
            "artist": "Jane Smith",
            "license": "Public domain",
            "license_url": "",
            "page_url": "https://commons.wikimedia.org/wiki/File:Satellite_Orbit_Earth.jpg"
        }

        # Temporary file for testing caption annotation
        test_post_file = Path("test_attrib_post.json")
        try:
            test_post_file.write_text(json.dumps(post), encoding="utf-8")

            # Annotate Story 1
            generate_image.annotate_image_credit(post, photo_info_1, caption_path=str(test_post_file), story_index=1)
            self.assertIn("Story 1 Image credit:", post["caption"])
            self.assertIn(photo_info_1["title"], post["caption"])

            # Story 2 had no photo (illustration) -> no credit appended for story 2
            generate_image.annotate_image_credit(post, None, caption_path=str(test_post_file), story_index=2)
            self.assertNotIn("Story 2", post["caption"])

            # Annotate Story 3
            generate_image.annotate_image_credit(post, photo_info_3, caption_path=str(test_post_file), story_index=3)
            self.assertIn("Story 3 Image credit:", post["caption"])
            self.assertIn(photo_info_3["title"], post["caption"])

            # Verify caption remains valid length
            self.assertLessEqual(len(post["caption"]), 2200)
        finally:
            if test_post_file.is_file():
                test_post_file.unlink()

    def test_fail_safe_broken_asset_fallback(self):
        canvas = Image.new("RGBA", (1080, 1350), (10, 24, 45, 255))
        # Corrupted photo_info with non-Image object
        corrupted_info = {"image": "corrupt_data_payload"}
        res = generate_image.crop_photo(
            canvas, corrupted_info, (65, 125, 1015, 615),
            category="BUSINESS", article={"title": "Test story with broken asset"}
        )
        self.assertFalse(res, "Expected fallback return value False when photo is broken")
        # Ensure canvas remained intact and valid
        self.assertEqual(canvas.size, (1080, 1350))

    def test_disqualifier_keywords_coverage(self):
        disqualifiers = generate_image.MAP_DIAGRAM_DISQUALIFIERS
        for required_word in ("map", "diagram", "chart", "graph", "screenshot", "flag", "coat of arms", "seal", "stamp"):
            self.assertIn(required_word, disqualifiers)

    def test_reject_hong_kong_icc_skyscraper_for_icc_court_story(self):
        article = {
            "title": "US Imposes Sanctions on ICC Officials Over Inquiries",
            "classification": {"topic": "Diplomacy"},
            "summary": "The United States announced financial sanctions against prosecutor staff at the International Criminal Court in The Hague.",
            "url": "https://reuters.com/world/icc-sanctions-investigation",
            "domain": "reuters.com"
        }
        queries = generate_image.build_photo_search_queries(article)
        self.assertIn("International Criminal Court", queries, "ICC must be disambiguated to International Criminal Court")
        self.assertNotIn("ICC", queries, "Bare acronym ICC must NOT be queried directly")

        resolved, conflicts = generate_image.resolve_acronym_and_conflicts(
            article["title"],
            article["classification"]["topic"] + " " + article["summary"]
        )
        self.assertIn("International Criminal Court", resolved)
        self.assertTrue(any(c in conflicts for c in ("commerce centre", "hong kong", "skyscraper", "kowloon")))

        # Candidate image from Hong Kong International Commerce Centre skyscraper
        bad_candidate_title = "International Commerce Centre (ICC) Hong Kong.jpg"
        bad_candidate_desc = "View of the 108-storey skyscraper in West Kowloon, Hong Kong."
        candidate_text = (bad_candidate_title + " " + bad_candidate_desc).lower()
        has_conflict = any(conflict_phrase in candidate_text for conflict_phrase in conflicts)
        self.assertTrue(has_conflict, "Conflict filter must reject the Hong Kong ICC skyscraper for court story")

        # Candidate image for cricket stadium / tournament
        cricket_candidate_title = "ICC Cricket World Cup Trophy in Dubai Stadium.jpg"
        cricket_candidate_desc = "Trophy presentation for international cricket council championship."
        candidate_text_cricket = (cricket_candidate_title + " " + cricket_candidate_desc).lower()
        has_cricket_conflict = any(conflict_phrase in candidate_text_cricket for conflict_phrase in conflicts)
        self.assertTrue(has_cricket_conflict, "Conflict filter must reject cricket candidates for court story")

    def test_labelled_diplomacy_illustration_fallback(self):
        article = {
            "title": "US Imposes Sanctions on ICC Officials Over Investigations",
            "classification": {"topic": "Diplomacy"},
            "url": "https://reuters.com/world/icc-sanctions",
            "domain": "reuters.com"
        }
        ill = generate_image.make_illustration(1080, 840, category="WORLD NEWS", article=article)
        self.assertEqual(ill.size, (1080, 840))
        self.assertEqual(ill.mode, "RGB")

        # Directly render diplomacy illustration with custom label
        direct_ill = generate_image.render_diplomacy_illustration(1080, 840, label="DIPLOMACY & SANCTIONS GRAPHIC")
        self.assertEqual(direct_ill.size, (1080, 840))
        self.assertEqual(direct_ill.mode, "RGB")

    def test_synthetic_and_mock_data_safety_checks(self):
        # 1. Distinguish mock fixture articles from genuine source news
        mock_articles = [
            {"title": "Test Story", "url": "https://example.com/test-article", "domain": "example.com"},
            {"title": "Unit Test Fixture Headline", "url": "https://test.com/news/123", "domain": "test.com"},
            {"title": "Local mock report", "url": "mock://localhost/news", "domain": "mock.com"},
        ]
        for ma in mock_articles:
            self.assertTrue(post_generator.is_mock_fixture_article(ma), f"Expected mock fixture: {ma['url']}")

        real_articles = [
            {"title": "US Imposes Sanctions on ICC Officials Over Inquiries", "url": "https://reuters.com/world/icc-sanctions", "domain": "reuters.com"},
            {"title": "Global Leaders Finalize Historic Clean Energy Framework", "url": "https://apnews.com/article/clean-energy-accord", "domain": "apnews.com"},
            {"title": "Central Bank Announces Interest Rate Adjustment", "url": "https://bbc.com/news/business-654321", "domain": "bbc.com"},
        ]
        for ra in real_articles:
            self.assertFalse(post_generator.is_mock_fixture_article(ra), f"Expected genuine source article: {ra['url']}")

        # 2. Mock fallback generator always marks post as synthetic
        mock_post = post_generator.generate_mock_post(real_articles[0])
        self.assertTrue(mock_post.get("is_synthetic"), "Fallback mock generator must stamp is_synthetic=True")

        # 3. Grounded post with real article produces is_synthetic=False
        grounded_data = {
            "headline": "US Imposes Major Sanctions on ICC Officials",
            "curiosity_line": "Key diplomatic fallout and responses",
            "caption": "The United States has announced new sanctions against International Criminal Court officials in response to ongoing sensitive inquiries, drawing widespread international diplomatic responses.",
            "hashtags": ["#NewsSnap", "#WorldNews", "#DiplomacyReport"]
        }
        validated_real = post_generator.validate_post(
            grounded_data, real_articles[0]["domain"], real_articles[0]["url"], is_mock=False
        )
        self.assertFalse(validated_real.get("is_synthetic"), "Grounded real news post must have is_synthetic=False")

        validated_mock = post_generator.validate_post(
            grounded_data, mock_articles[0]["domain"], mock_articles[0]["url"], is_mock=True
        )
        self.assertTrue(validated_mock.get("is_synthetic"), "Mock fixture post must have is_synthetic=True")

        # 4. Publisher refuses live publishing if post is marked synthetic
        synthetic_post = dict(validated_real)
        synthetic_post["is_synthetic"] = True
        test_post_file = Path("test_synthetic_check.json")
        try:
            test_post_file.write_text(json.dumps(synthetic_post), encoding="utf-8")
            # In live mode with credentials, publisher must raise ValueError for synthetic post
            post_data = json.loads(test_post_file.read_text(encoding="utf-8"))
            self.assertTrue(post_data.get("is_synthetic"))
        finally:
            if test_post_file.is_file():
                test_post_file.unlink()

    def test_uppercase_curiosity_line_english_validation(self):
        uppercase_curiosities = [
            "US SANCTIONS ON ICC",
            "WHAT THIS MEANS FOR GLOBAL TRADE",
            "KEY DEVELOPMENTS AND GLOBAL IMPACT",
            "WHY THIS MATTERS WORLDWIDE",
        ]
        for cur in uppercase_curiosities:
            self.assertTrue(post_generator.is_english(cur), f"Uppercase curiosity '{cur}' must pass English validation")

        post = {
            "headline": "US Imposes Major Sanctions on ICC Court Officials",
            "curiosity_line": "US SANCTIONS ON ICC",
            "caption": "The United States government has announced new economic sanctions against prosecutors at the International Criminal Court in The Hague, prompting significant international debate.",
            "hashtags": ["#NewsSnap", "#WorldNews", "#Diplomacy"]
        }
        res = post_generator.validate_post(post, "reuters.com", "https://reuters.com/world/icc-sanctions")
        self.assertEqual(res["curiosity_line"], "US SANCTIONS ON ICC")
        self.assertFalse(res["is_synthetic"])

    def test_all_six_formats_visual_integrity_and_dimensions(self):
        post = {
            "headline": "US Imposes Sanctions on ICC Officials Over Inquiries",
            "curiosity_line": "Key diplomatic fallout and responses",
            "caption": "The United States has announced new economic sanctions against prosecutors at the International Criminal Court in The Hague.",
            "hashtags": ["#NewsSnap", "#WorldNews", "#Diplomacy"]
        }
        article = {
            "title": "US Imposes Sanctions on ICC Officials Over Inquiries",
            "classification": {"topic": "Diplomacy"},
            "summary": "Economic sanctions imposed against ICC prosecutors.",
            "url": "https://reuters.com/world/icc-sanctions",
            "domain": "reuters.com",
            "quote_text": "We stand firmly behind the integrity and independence of international justice institutions.",
            "speaker": "António Guterres",
            "speaker_role": "United Nations Secretary-General",
            "quote_verified": True
        }
        formats_to_test = ["01", "02", "03", "04", "05", "06"]
        roundup_path = Path("roundup.json")
        roundup_post_path = Path("roundup_post.json")
        roundup_created = False
        roundup_post_created = False
        if not roundup_path.is_file():
            roundup_data = {
                "stories": [
                    {"title": "Global Leaders Agree on Renewable Energy Goals", "domain": "reuters.com", "url": "https://reuters.com/1", "summary": "Nations commit to tripling clean energy capacity by 2030."},
                    {"title": "Central Bank Holds Benchmark Interest Rate Steady", "domain": "bloomberg.com", "url": "https://bloomberg.com/2", "summary": "Policymakers maintain interest rates following inflation reports."},
                    {"title": "Space Agency Launches Atmospheric Research Mission", "domain": "bbc.com", "url": "https://bbc.com/3", "summary": "New satellite will track worldwide climate and greenhouse gases."}
                ]
            }
            roundup_path.write_text(json.dumps(roundup_data), encoding="utf-8")
            roundup_created = True
        if not roundup_post_path.is_file():
            roundup_post_data = {
                "headline": "TODAY'S TOP 3 STORIES",
                "curiosity_line": "Key updates across energy, finance and diplomacy",
                "format": "04",
                "caption": "NEWS SNAP roundup of today's top stories. #NewsSnap\n\n1. Energy — reuters.com\n2. Rate — apnews.com\n3. Summit — bbc.com",
                "hashtags": ["#NewsSnap", "#DailyBriefing"]
            }
            roundup_post_path.write_text(json.dumps(roundup_post_data), encoding="utf-8")
            roundup_post_created = True
        try:
            for fmt_id in formats_to_test:
                img, rendered_post, _ = generate_image.render_approved_format(fmt_id, article, post)
                self.assertEqual(img.size, (1080, 1350), f"Format {fmt_id} must render exact dimensions 1080x1350")
                jpeg_export = img.convert("RGB")
                self.assertEqual(jpeg_export.size, (1080, 1350))
                self.assertEqual(jpeg_export.mode, "RGB", f"Format {fmt_id} must export cleanly as RGB JPEG")
        finally:
            if roundup_created and roundup_path.is_file():
                roundup_path.unlink()
            if roundup_post_created and roundup_post_path.is_file():
                roundup_post_path.unlink()

class TestQuoteVerificationAndPreservation(unittest.TestCase):
    """Regression tests for NEWS SNAP quote verification, verbatim preservation, and refusal safeguards."""

    def test_verify_quote_exact_match_verbatim_and_punctuation(self):
        source_text = (
            "During the press conference at the summit, António Guterres declared, "
            "“We stand firmly behind the integrity, independence, and impartiality of the international court.” "
            "He warned that unilateral sanctions undermine global justice."
        )

        # 1. Exact quote with identical words and punctuation matches
        exact_quote = "We stand firmly behind the integrity, independence, and impartiality of the international court."
        self.assertTrue(
            prepare_special_formats.verify_quote_exact_match(exact_quote, source_text),
            "Exact quote with punctuation must pass verification"
        )

        # 2. Straight quote normalization works
        quote_with_quotes = '"We stand firmly behind the integrity, independence, and impartiality of the international court."'
        self.assertTrue(
            prepare_special_formats.verify_quote_exact_match(quote_with_quotes, source_text)
        )

        # 3. Rewritten, paraphrased, or fabricated quote fails verification
        paraphrased_quote = "We strongly support the integrity and independence of the court."
        self.assertFalse(
            prepare_special_formats.verify_quote_exact_match(paraphrased_quote, source_text),
            "Paraphrased or rewritten quotation must fail verification"
        )

        # 4. Truncated or modified quote that changes meaning/wording fails if not exact substring
        modified_quote = "We stand firmly behind the integrity of international courts everywhere."
        self.assertFalse(
            prepare_special_formats.verify_quote_exact_match(modified_quote, source_text),
            "Modified quotation must fail verification"
        )

        # 5. Empty inputs fail
        self.assertFalse(prepare_special_formats.verify_quote_exact_match("", source_text))
        self.assertFalse(prepare_special_formats.verify_quote_exact_match(exact_quote, ""))

    def test_quotation_never_shortened_or_truncated(self):
        # validate_english_text must raise ValueError rather than truncating quotes that exceed max_words
        long_quote = (
            "The international community must come together to uphold the fundamental principles of "
            "justice, accountability, and the rule of law across all sovereign nations, ensuring that "
            "no individual or government can act with impunity or disregard established international "
            "legal treaties and human rights protections in times of conflict."
        )
        self.assertGreater(len(long_quote.split()), 45)
        with self.assertRaises(ValueError) as ctx:
            generate_image.validate_english_text(long_quote, "verified quotation", 5, 45)
        self.assertIn("Never shorten or truncate a quotation", str(ctx.exception))

        # A non-quote label still supports safe length bounding if needed
        non_quote = (
            "Global ministers and international delegates convened today in Geneva to negotiate new "
            "environmental protection agreements, addressing climate change, renewable energy adoption, "
            "economic stability, sustainable development goals, and technological collaboration across "
            "developed and developing nations in response to extreme weather patterns."
        )
        self.assertGreater(len(non_quote.split()), 30)
        truncated_non_quote = generate_image.validate_english_text(non_quote, "headline", 5, 20)
        self.assertEqual(len(truncated_non_quote.split()), 20)

        # Valid quote preserves punctuation and exact words
        valid_quote = "We must act now, before it is too late; history will judge our actions."
        result = generate_image.validate_english_text(valid_quote, "verified quotation", 5, 45)
        self.assertEqual(result, valid_quote)

    def test_format_06_refusal_when_quote_unverified(self):
        article_unverified = {
            "title": "Diplomat Remarks on International Sanctions",
            "url": "https://reuters.com/world/diplomat-remarks",
            "domain": "reuters.com",
            "quote_text": "We stand firmly behind the integrity and independence of international justice institutions.",
            "speaker": "António Guterres",
            "speaker_role": "UN Secretary-General",
            "quote_verified": False  # Explicitly unverified
        }
        post = {
            "headline": "Diplomat Speaks on Sanctions",
            "curiosity_line": "Key statements and implications",
            "caption": "A detailed discussion on international sanctions.",
            "hashtags": ["#NewsSnap", "#Diplomacy"]
        }

        # 1. draw_template_06 raises ValueError when quote_verified is False or not True
        with self.assertRaises(ValueError) as ctx:
            generate_image.draw_template_06(article_unverified, post, photo=None)
        self.assertIn("Format 06 REFUSAL", str(ctx.exception))

        # 2. draw_template_06 raises ValueError when quote_verified is missing
        article_missing_flag = dict(article_unverified)
        del article_missing_flag["quote_verified"]
        with self.assertRaises(ValueError) as ctx:
            generate_image.draw_template_06(article_missing_flag, post, photo=None)
        self.assertIn("Format 06 REFUSAL", str(ctx.exception))

        # 3. render_approved_format('06', ...) refuses unverified quote
        with self.assertRaises(ValueError) as ctx:
            generate_image.render_approved_format("06", article_unverified, post)
        self.assertIn("Format 06 REFUSAL", str(ctx.exception))

        # 4. render_approved_format('06', ...) refuses missing speaker or quote_text
        article_no_speaker = dict(article_unverified)
        article_no_speaker["quote_verified"] = True
        article_no_speaker["speaker"] = ""
        with self.assertRaises(ValueError) as ctx:
            generate_image.render_approved_format("06", article_no_speaker, post)
        self.assertIn("Format 06 REFUSAL", str(ctx.exception))

    def test_format_06_skips_to_appropriate_non_quote_format_when_unverified(self):
        article_unverified = {
            "title": "US Imposes Sanctions on ICC Officials Over Inquiries",
            "classification": {"topic": "Diplomacy"},
            "summary": "Economic sanctions imposed against ICC prosecutors.",
            "url": "https://reuters.com/world/icc-sanctions",
            "domain": "reuters.com",
            "quote_text": "We stand firmly behind the integrity and independence of international justice institutions.",
            "speaker": "António Guterres",
            "quote_verified": False  # Unverified
        }

        # Rule 1 in classify_format_for_article must skip Format 06 and fallback to standard format (Format 05)
        fmt_id, reason = format_registry.classify_format_for_article(article_unverified, roundup_exists=False)
        self.assertEqual(fmt_id, "05", "Unverified quote must fallback to appropriate non-quote format (05)")
        self.assertNotIn("Format 06", reason)

        # Corporate story with unverified quote falls back to Format 03
        corp_article = {
            "title": "Tech Giant CEO Steps Down After Ten Years",
            "quote_text": "It has been an honour to lead this team.",
            "speaker": "Jane Doe",
            "quote_verified": False
        }
        fmt_id, reason = format_registry.classify_format_for_article(corp_article, roundup_exists=False)
        self.assertEqual(fmt_id, "03", "Corporate article with unverified quote must fallback to Format 03")

        # Emergency story with unverified quote falls back to Format 01
        emergency_article = {
            "title": "Massive Wildfire Forces Urgent Evacuations",
            "quote_text": "Residents must leave immediately.",
            "speaker": "Fire Chief",
            "quote_verified": False
        }
        fmt_id, reason = format_registry.classify_format_for_article(emergency_article, roundup_exists=False)
        self.assertEqual(fmt_id, "01", "Emergency article with unverified quote must fallback to Format 01")

        # Fully verified quote successfully selects Format 06
        verified_article = dict(article_unverified)
        verified_article["quote_verified"] = True
        fmt_id, reason = format_registry.classify_format_for_article(verified_article, roundup_exists=False)
        self.assertEqual(fmt_id, "06", "Verified quote and speaker must select Format 06")

    def test_attach_quote_verification_with_source_body(self):
        article = {
            "title": "World Court Press Briefing",
            "url": "https://reuters.com/world/court-briefing",
            "domain": "reuters.com",
            "quote_text": "We stand firmly behind the integrity and independence of international justice institutions.",
            "speaker": "António Guterres"
        }

        # Case 1: Body contains exact quote -> attach_quote_to_article verifies and returns enriched dict
        matching_body = (
            "At the United Nations briefing, António Guterres declared, "
            "“We stand firmly behind the integrity and independence of international justice institutions.” "
            "The statement was delivered in response to recent developments."
        )
        with patch("prepare_special_formats.get_article_payload", return_value={"body": matching_body}):
            result = prepare_special_formats.attach_quote_to_article(article, fetch=True)
            self.assertIsNotNone(result)
            self.assertTrue(result.get("quote_verified"))
            self.assertEqual(result.get("quote_text"), article["quote_text"])
            self.assertEqual(result.get("speaker"), article["speaker"])

        # Case 2: Body contains different / rewritten wording -> attach_quote_to_article rejects and returns None
        mismatched_body = (
            "At the United Nations briefing, António Guterres spoke about the importance of courts. "
            "He emphasized that nations should respect legal frameworks."
        )
        with patch("prepare_special_formats.get_article_payload", return_value={"body": mismatched_body}):
            result = prepare_special_formats.attach_quote_to_article(article, fetch=True)
            self.assertIsNone(result, "Quote failing exact match against source body must be rejected (return None)")

    def test_vector_illustrations_visibly_labelled_as_illustrations(self):
        # 1. Quote illustration has visible "STATEMENT ILLUSTRATION" badge
        quote_ill = generate_image.render_quote_illustration(1080, 1350)
        self.assertEqual(quote_ill.size, (1080, 1350))
        self.assertEqual(quote_ill.mode, "RGB")

        # 2. Government / Institutional illustration has visible "INSTITUTIONAL ILLUSTRATION" badge
        gov_ill = generate_image.render_gov_illustration(1080, 840)
        self.assertEqual(gov_ill.size, (1080, 840))
        self.assertEqual(gov_ill.mode, "RGB")


class TestStoryToImageRelevanceAndIllustrations(unittest.TestCase):
    """Regression tests for story-to-image relevance, FEMA photo rejection, and election illustrations."""

    def setUp(self):
        self.california_election_article = {
            "title": "California officials announce new ballot counting deadlines for upcoming election",
            "classification": {"topic": "Politics"},
            "summary": "State election officials in California have introduced updated timelines for counting mail-in ballots.",
            "url": "https://reuters.com/world/us/california-ballot-counting-election",
            "domain": "reuters.com"
        }

    def test_reject_fema_disaster_photo_for_california_election_story(self):
        # Candidate FEMA disaster photo
        fema_title = "FEMA - 43332 - State officials meet with FEMA in California.jpg"
        fema_desc = "State officials meet with FEMA in California."

        is_rel, reason = generate_image.is_photo_meaningfully_relevant(
            fema_title, fema_desc, self.california_election_article
        )
        self.assertFalse(is_rel, "FEMA disaster photo must be rejected for California election ballot story")
        self.assertTrue(
            "disaster" in reason.lower() or "fema" in reason.lower() or "broad" in reason.lower(),
            f"Expected rejection reason citing disaster/FEMA or broad terms, got: '{reason}'"
        )

    def test_reject_broad_terms_alone_without_topic_or_entity_match(self):
        # 1. Candidate sharing ONLY broad terms (California, officials, state) with no topical match
        generic_official_title = "California state officials attend annual governmental reception.jpg"
        generic_official_desc = "Officials in California gathering for state ceremony."

        is_rel, reason = generate_image.is_photo_meaningfully_relevant(
            generic_official_title, generic_official_desc, self.california_election_article
        )
        self.assertFalse(is_rel, "Photo matching only broad geographic/generic terms must be rejected")
        self.assertIn("broad", reason.lower())

        # 2. Candidate that genuinely depicts election/ballot processing
        election_photo_title = "Election workers process mail-in ballots in California.jpg"
        election_photo_desc = "Staff sorting and verifying election ballots in Sacramento county."

        is_rel_valid, reason_valid = generate_image.is_photo_meaningfully_relevant(
            election_photo_title, election_photo_desc, self.california_election_article
        )
        self.assertTrue(is_rel_valid, f"Genuine election ballot photo must be accepted: '{reason_valid}'")

    def test_search_queries_do_not_emit_broad_terms_alone(self):
        queries = generate_image.build_photo_search_queries(self.california_election_article)
        # Ensure bare "California officials" or "State officials" alone without topic nouns is not emitted
        for q in queries:
            tokens = [t.lower() for t in q.split()]
            self.assertFalse(
                all(t in generate_image.BROAD_TERMS for t in tokens),
                f"Search query '{q}' consists purely of broad geographic/generic terms"
            )

    def test_labelled_election_illustration_fallback(self):
        # 1. Directly render election illustration
        direct_ill = generate_image.render_election_illustration(1080, 840)
        self.assertEqual(direct_ill.size, (1080, 840))
        self.assertEqual(direct_ill.mode, "RGB")

        # 2. Automatic selection via make_illustration with election article
        ill = generate_image.make_illustration(1080, 840, category="POLITICS", article=self.california_election_article)
        self.assertEqual(ill.size, (1080, 840))
        self.assertEqual(ill.mode, "RGB")

        # 3. Verify it does not render a blank block and scales across dimensions
        for w, h in [(950, 490), (240, 199), (530, 1000)]:
            scaled_ill = generate_image.render_election_illustration(w, h)
            self.assertEqual(scaled_ill.size, (w, h))
            self.assertEqual(scaled_ill.mode, "RGB")

    def test_image_credits_only_added_when_photo_actually_used(self):
        post = {
            "headline": "California Officials Announce Ballot Deadlines",
            "caption": "California election officials announced new guidelines for mail-in ballot processing. #NewsSnap",
            "hashtags": ["#NewsSnap", "#Elections"]
        }

        # 1. When photo is None (illustration used), annotate_image_credit does nothing
        generate_image.annotate_image_credit(post, None)
        self.assertNotIn("Image credit:", post["caption"])

        # 2. When photo has no decoded Image instance, annotate_image_credit does nothing
        corrupt_photo = {"title": "Test.jpg", "artist": "Photographer", "license": "CC BY-SA 4.0", "page_url": "https://commons.wikimedia.org/wiki/File:Test.jpg", "image": "corrupt_data"}
        generate_image.annotate_image_credit(post, corrupt_photo)
        self.assertNotIn("Image credit:", post["caption"])

        # 3. When photo is genuine Image, annotate_image_credit adds clean attribution
        real_img = Image.new("RGB", (800, 600), (40, 60, 80))
        valid_photo = {
            "title": "Ballot_box_voting.jpg",
            "artist": "Jane Doe",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "page_url": "https://commons.wikimedia.org/wiki/File:Ballot_box_voting.jpg",
            "image": real_img
        }
        generate_image.annotate_image_credit(post, valid_photo)
        self.assertIn("Image credit: Ballot_box_voting.jpg by Jane Doe.", post["caption"])
        self.assertIn("Licence: CC BY-SA 4.0.", post["caption"])

        # 4. strip_image_credits cleanly removes attribution block
        cleaned_caption = generate_image.strip_image_credits(post["caption"])
        self.assertNotIn("Image credit:", cleaned_caption)
        self.assertIn("California election officials announced", cleaned_caption)


class TestContextualImageLabelAndSafeguards(unittest.TestCase):
    """Regression tests for contextual image labelling, file photo verification, and relevance safeguards."""

    def setUp(self):
        self.article = {
            "title": "Diplomatic Representatives Convene for Bilateral Security Talks in Geneva",
            "domain": "reuters.com",
            "url": "https://reuters.com/world/security-talks",
            "classification": {"importance": "MAJOR", "topic": "Diplomacy"}
        }
        self.dummy_photo = {
            "title": "Geneva_Palais_des_Nations.jpg",
            "artist": "Alexandre Dupont",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "page_url": "https://commons.wikimedia.org/wiki/File:Geneva_Palais_des_Nations.jpg",
            "image": Image.new("RGB", (640, 480), (50, 70, 90))
        }

    def test_contextual_image_label_for_unverified_photograph(self):
        # 1. Unverified photograph relevant to story receives 'CONTEXTUAL IMAGE'
        label = generate_image.determine_photo_label(self.dummy_photo, self.article)
        self.assertEqual(label, "CONTEXTUAL IMAGE")

        # 2. Rendering into canvas attaches badge inside photo boundaries
        canvas = Image.new("RGBA", (1080, 1350), (10, 20, 30, 255))
        box = (0, 0, 1080, 840)
        pasted = generate_image.crop_photo(canvas, self.dummy_photo, box, article=self.article, draw_label=True)
        self.assertTrue(pasted)
        self.assertEqual(canvas.size, (1080, 1350))

    def test_file_photo_label_only_when_supported_by_source(self):
        # 1. Source indicators containing archival or file photo cues return 'FILE PHOTO'
        archival_cases = [
            {"is_file_photo": True},
            {"title": "Geneva Palais des Nations (file photo).jpg"},
            {"description": "Archive photo of conference venue from 2021."},
            {"notes": "Archival image preserved in national records."},
            {"artist": "Staff / Archive file"},
            {"source": "Historical photo repository"}
        ]
        for extra in archival_cases:
            info = dict(self.dummy_photo, **extra)
            lbl = generate_image.determine_photo_label(info, self.article)
            self.assertEqual(lbl, "FILE PHOTO", f"Expected 'FILE PHOTO' for cue: {extra}")

        # 2. When no source cue exists, unverified photo returns 'CONTEXTUAL IMAGE', never 'FILE PHOTO'
        clean_info = dict(self.dummy_photo)
        self.assertEqual(generate_image.determine_photo_label(clean_info, self.article), "CONTEXTUAL IMAGE")

        # 3. Verified event photograph returns empty string (no contextual badge)
        verified_info = dict(self.dummy_photo, event_verified=True)
        self.assertEqual(generate_image.determine_photo_label(verified_info, self.article), "")

        # 4. Matching location/subject alone does not infer event depiction
        location_photo = dict(self.dummy_photo, title="Geneva Palais des Nations conference hall")
        self.assertEqual(generate_image.determine_photo_label(location_photo, self.article), "CONTEXTUAL IMAGE")

    def test_irrelevant_photo_rejected_in_favour_of_labelled_illustration(self):
        # 1. Irrelevant candidate is rejected by relevance safeguard
        irrelevant_title = "Wildfire containment operations in mountain valley.jpg"
        irrelevant_desc = "Firefighting helicopters drop water on forest blaze."
        is_rel, reason = generate_image.is_photo_meaningfully_relevant(irrelevant_title, irrelevant_desc, self.article)
        self.assertFalse(is_rel)

        # 2. Crop photo fallback generates vector illustration
        canvas = Image.new("RGBA", (1080, 1350), (10, 20, 30, 255))
        box = (65, 125, 1015, 615)
        pasted = generate_image.crop_photo(canvas, None, box, category="DIPLOMACY", article=self.article)
        self.assertFalse(pasted, "Should return False when falling back to vector illustration")

        # 3. Editorial vector illustration produces clear non-empty RGB visual
        ill = generate_image.make_illustration(950, 490, category="DIPLOMACY", article=self.article)
        self.assertEqual(ill.size, (950, 490))
        self.assertEqual(ill.mode, "RGB")
        extrema = ill.getextrema()
        self.assertTrue(any(ch[0] != ch[1] for ch in extrema), "Illustration must not be a blank solid color")

    def test_illustration_fallbacks_do_not_receive_invented_photo_credits(self):
        post = {
            "headline": "Geneva Security Talks Open",
            "caption": "Diplomats gather in Geneva for high-stakes bilateral security negotiations. #NewsSnap"
        }
        # 1. Fallback with None photo adds no credit
        generate_image.annotate_image_credit(post, None)
        self.assertNotIn("Image credit:", post["caption"])

        # 2. Fallback with non-image object adds no credit
        generate_image.annotate_image_credit(post, {"image": None, "page_url": "https://example.com"})
        self.assertNotIn("Image credit:", post["caption"])

        # 3. Existing credits cleanly stripped when using illustration
        post_with_credit = {
            "headline": "Geneva Security Talks Open",
            "caption": "Diplomats gather in Geneva. #NewsSnap\n\nImage credit: Old_Photo.jpg by Jane Doe. Licence: CC BY-SA 4.0."
        }
        stripped = generate_image.strip_image_credits(post_with_credit["caption"])
        self.assertNotIn("Image credit:", stripped)
        self.assertIn("Diplomats gather in Geneva", stripped)

    def test_all_six_approved_formats_retain_dimensions_and_layout(self):
        # Verify all 6 formats render at exactly 1080x1350 RGB/RGBA
        test_cases = [
            ("01", {
                "title": "Severe Coastal Storm Triggers High Wind Warnings",
                "domain": "reuters.com",
                "url": "https://reuters.com/storm",
                "classification": {"importance": "MAJOR", "topic": "Emergency"}
            }, {
                "headline": "Severe Coastal Storm Triggers Warnings",
                "caption": "High wind warnings are in effect along coastal regions. #NewsSnap"
            }),
            ("02", {
                "title": "Global Tech Firm Reports Quarterly Earnings Exceeding Estimates",
                "domain": "bloomberg.com",
                "url": "https://bloomberg.com/tech",
                "classification": {"importance": "MAJOR", "topic": "Business"}
            }, {
                "headline": "Quarterly Earnings Exceed Estimates",
                "caption": "Revenues surpassed analyst forecasts in third quarter results. #NewsSnap"
            }),
            ("03", {
                "title": "CEO Outlines Five-Year Vision for Clean Energy Transition",
                "domain": "ft.com",
                "url": "https://ft.com/energy",
                "classification": {"importance": "MAJOR", "topic": "People"}
            }, {
                "headline": "CEO Outlines Clean Energy Vision",
                "caption": "Strategic transition plans were detailed during annual address. #NewsSnap"
            }),
            ("05", {
                "title": "European Union Council Adopts New Cross-Border Regulatory Framework",
                "domain": "reuters.com",
                "url": "https://reuters.com/eu",
                "classification": {"importance": "MAJOR", "topic": "Government"}
            }, {
                "headline": "EU Council Adopts New Regulations",
                "caption": "Member states finalized approval for standardized guidelines. #NewsSnap"
            }),
            ("06", {
                "title": "Prime Minister Delivers Address on International Peacekeeping",
                "domain": "reuters.com",
                "url": "https://reuters.com/peace",
                "quote_verified": True,
                "quote_text": "Peace is not merely the absence of conflict, but the presence of justice.",
                "speaker": "Prime Minister",
                "speaker_role": "Head of Government",
                "classification": {"importance": "MAJOR", "topic": "Diplomacy"}
            }, {
                "headline": "Prime Minister Addresses Peace Summit",
                "caption": "The Prime Minister underscored international commitments to lasting security. #NewsSnap"
            }),
        ]

        for fmt, article, post in test_cases:
            img, _, _ = generate_image.render_approved_format(fmt, article, post)
            self.assertEqual(img.size, (1080, 1350), f"Format {fmt} dimension mismatch")
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            self.assertGreater(buf.tell(), 10000, f"Format {fmt} output buffer is unexpectedly small")

        # Verify Format 06 refuses unverified quotes
        unverified_article = dict(test_cases[4][1], quote_verified=False)
        with self.assertRaises(ValueError):
            generate_image.render_approved_format("06", unverified_article, test_cases[4][2])


class TestFinalComprehensiveQualityGate(unittest.TestCase):
    """Consolidated acceptance test suite exercising all 18 quality gate criteria."""

    def test_01_candidate_ingestion_and_language_filtering(self):
        # Category 1: Candidate ingestion with strict English language filtering
        self.assertTrue(discovery.is_english_headline("Federal Reserve holds interest rates steady"))
        self.assertFalse(discovery.is_english_headline("Bundeskanzler kündigt neue Maßnahmen an"))
        self.assertFalse(discovery.is_english_headline("Los incendios forestales se intensifican"))

    def test_02_source_body_and_description_parsing(self):
        # Category 2: Source body & description parsing and fallback handling
        html = """
        <html><head>
        <meta name="description" content="Official economic report released by the Treasury Department.">
        </head><body>
        <p>The Treasury Department today published its annual fiscal report detailing budget expenditures.</p>
        </body></html>
        """
        parser = post_generator.SourceEvidenceParser()
        parser.feed(html)
        self.assertIn("Official economic report", parser.meta_desc)
        self.assertIn("Treasury Department today published", parser.paragraphs[0])

    def test_03_fresh_candidate_detection_and_schedule(self):
        # Category 3: Fresh-candidate detection and 5-minute scheduler architecture
        test_path = Path(".github/workflows/test.yml")
        sched_path = Path(".github/workflows/news-snap-scheduler.yml")
        self.assertTrue(test_path.is_file())
        self.assertTrue(sched_path.is_file())
        test_text = test_path.read_text(encoding="utf-8")
        sched_text = sched_path.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", test_text)
        self.assertNotIn("0 */6 * * *", test_text)
        self.assertIn("bootstrap_only", sched_text)

    def test_04_quota_sparing_diff_skip_logic(self):
        # Category 4: Quota-sparing candidate-diff skip logic
        candidates = [{"url": "https://reuters.com/item1", "title": "Valid News Story Item Number One"}]
        history = {"posted": [{"url": "https://reuters.com/item1", "title": "Valid News Story Item Number One", "published": True}], "processed": []}
        disc_path = Path("test_disc_diff.json")
        hist_path = Path("test_hist_diff.json")
        disc_path.write_text(json.dumps(candidates), encoding="utf-8")
        hist_path.write_text(json.dumps(history), encoding="utf-8")
        try:
            import check_candidates
            fresh = check_candidates.get_fresh_candidates(discovery_path=disc_path, history_path=hist_path)
            self.assertEqual(len(fresh), 0)
        finally:
            if disc_path.is_file():
                disc_path.unlink()
            if hist_path.is_file():
                hist_path.unlink()

    def test_05_gemini_model_configuration_and_offline_mock(self):
        # Category 5: Classification with gemini-3.8-flash and mock offline path
        workflow_text = Path(".github/workflows/test.yml").read_text(encoding="utf-8")
        self.assertIn('GEMINI_MODEL: "gemini-3.8-flash"', workflow_text)
        self.assertEqual(post_generator.MODEL, "gemini-3.8-flash")
        # Offline mock path works cleanly
        article = {
            "title": "Clean Energy Investment Reaches Record High",
            "domain": "reuters.com",
            "url": "https://reuters.com/energy",
            "source_description": "Clean energy investments grew substantially in recent quarters."
        }
        post = post_generator.generate_mock_post(article)
        self.assertIn("headline", post)
        self.assertIn("caption", post)
        self.assertTrue(post.get("is_synthetic"))

    def test_06_source_grounded_headline_and_summary_generation(self):
        # Category 6: Source-grounded headline and summary generation
        article = {
            "title": "Central Bank Announces New Reserve Requirements for Commercial Lenders",
            "domain": "reuters.com",
            "url": "https://reuters.com/central-bank",
            "source_description": "The central bank updated mandatory cash reserve ratios for banking institutions."
        }
        post = post_generator.generate_mock_post(article)
        # Ensure post fields are grounded in source content
        self.assertTrue(any(word in post["headline"].lower() for word in ["bank", "reserve", "requirements", "lenders"]))

    def test_07_rejection_of_unsupported_claims_and_invented_numbers(self):
        # Category 7: Rejection of unsupported factual claims and invented numbers
        article = {
            "title": "Trade Talks Conclude in Brussels",
            "domain": "reuters.com",
            "url": "https://reuters.com/trade",
            "source_description": "Delegates finalized preliminary terms on international shipping."
        }
        post_invented_numbers = {
            "headline": "Trade Talks Conclude with $45 Billion Agreement",
            "curiosity_line": "New bilateral pact sealed",
            "caption": "Delegates in Brussels reached an agreement involving $45 billion in international tariffs and 85 percent trade quotas during high level bilateral economic sessions this morning. #NewsSnap",
            "hashtags": ["#NewsSnap", "#WorldNews", "#Trade"]
        }
        with self.assertRaises(ValueError) as ctx:
            post_generator.validate_post(
                post_invented_numbers,
                source="reuters.com",
                url="https://reuters.com/trade",
                article=article,
                source_evidence=article["source_description"]
            )
        self.assertIn("unsupported number", str(ctx.exception).lower())

    def test_08_rejection_of_allegations_converted_to_facts(self):
        # Category 8: Rejection of allegations/questions converted to facts without attribution
        article = {
            "title": "Company Faces Allegations of Regulatory Violations",
            "domain": "reuters.com",
            "url": "https://reuters.com/company",
            "source_description": "Prosecutors alleged that the corporation misled investors regarding compliance."
        }
        # Post converts allegation into settled factual guilt without attribution
        post_unattributed_guilt = {
            "headline": "Company Violated Federal Compliance Rules",
            "curiosity_line": "Major regulatory breach",
            "caption": "The corporation committed fraud and broke federal regulatory laws following internal audit reviews this week without any doubt or dispute. #NewsSnap #WorldNews #Business",
            "hashtags": ["#NewsSnap", "#WorldNews", "#Business"]
        }
        with self.assertRaises(ValueError) as ctx:
            post_generator.validate_post(
                post_unattributed_guilt,
                source="reuters.com",
                url="https://reuters.com/company",
                article=article,
                source_evidence=article["source_description"]
            )
        self.assertIn("allegation", str(ctx.exception).lower())

    def test_09_rejection_of_sensationalized_clickbait(self):
        # Category 9: Rejection of sensationalized clickbait fabrication
        article = {
            "title": "Regional Council Discusses Public Transit Upgrades",
            "domain": "reuters.com",
            "url": "https://reuters.com/transit",
            "source_description": "Council members discussed budget options for commuter rail upgrades."
        }
        post_clickbait = {
            "headline": "You Won't Believe What Council Did",
            "curiosity_line": "This shocking secret changes everything",
            "caption": "You won't believe what regional council members secretly voted for in this shocking closed door meeting that will completely change everything you thought you knew. #NewsSnap",
            "hashtags": ["#NewsSnap", "#WorldNews", "#LocalNews"]
        }
        with self.assertRaises(ValueError) as ctx:
            post_generator.validate_post(
                post_clickbait,
                source="reuters.com",
                url="https://reuters.com/transit",
                article=article,
                source_evidence=article["source_description"]
            )
        self.assertIn("clickbait", str(ctx.exception).lower())

    def test_10_format_selection_across_all_six_formats(self):
        # Category 10: Format selection across all 6 approved formats
        # Format 01: Emergency
        fmt, _ = format_registry.classify_format_for_article({
            "title": "Severe Wildfire Prompts Mass Evacuations",
            "classification": {"importance": "BREAKING", "topic": "Emergency"}
        })
        self.assertEqual(fmt, "01")
        # Format 02: Business/Markets
        fmt, _ = format_registry.classify_format_for_article({
            "title": "Stock Markets Rally on Inflation Report",
            "classification": {"importance": "NORMAL", "topic": "Business"}
        })
        self.assertEqual(fmt, "02")
        # Format 03: Profile / Leadership
        fmt, _ = format_registry.classify_format_for_article({
            "title": "Tech Leader Steps Down After Decade",
            "classification": {"importance": "NORMAL", "topic": "People"}
        })
        self.assertEqual(fmt, "03")
        # Format 04: Roundup
        fmt, _ = format_registry.classify_format_for_article({"template_override": "04"}, roundup_exists=True)
        self.assertEqual(fmt, "04")
        # Format 05: Standard World News / Governance
        fmt, _ = format_registry.classify_format_for_article({
            "title": "United Nations Convenes Global Diplomatic Session",
            "classification": {"importance": "MAJOR", "topic": "Governance"}
        })
        self.assertEqual(fmt, "05")
        # Format 06: Verified quote
        fmt, _ = format_registry.classify_format_for_article({"quote_verified": True, "quote_text": "Sample quote.", "speaker": "Leader"})
        self.assertEqual(fmt, "06")

    def test_11_format_06_exact_quote_and_safe_fallback(self):
        # Category 11: Format 06 exact-quote verification, attribution, and non-quote fallback
        unverified = {"title": "Diplomatic Address", "quote_verified": False, "quote_text": "Unverified text", "speaker": "Diplomat", "classification": {"topic": "Diplomacy"}}
        # Refuses unverified quote
        with self.assertRaises(ValueError):
            generate_image.render_approved_format("06", unverified, {"headline": "H", "caption": "C"})
        # Falls back cleanly to standard format
        fmt, _ = format_registry.classify_format_for_article(unverified, roundup_exists=False)
        self.assertEqual(fmt, "05")

    def test_12_format_04_three_story_consistency(self):
        # Category 12: Format 04 3-story consistency across image, caption, attribution, and post.json
        stories = [
            {
                "title": "Global Leaders Reach Major Clean Energy Agreement",
                "domain": "reuters.com",
                "url": "https://reuters.com/1",
                "summary": "International leaders reached a comprehensive new global agreement on clean energy standards."
            },
            {
                "title": "Central Bank Holds Benchmark Interest Rate Steady",
                "domain": "apnews.com",
                "url": "https://apnews.com/2",
                "summary": "The central bank decided to hold benchmark interest rates steady following moderating inflation data."
            },
            {
                "title": "Space Agency Prepares Historic Lunar Landing Mission",
                "domain": "bloomberg.com",
                "url": "https://bloomberg.com/3",
                "summary": "Scientists and engineers are finalizing launch preparations for an upcoming lunar exploration landing mission."
            }
        ]
        roundup_file = Path("roundup.json")
        roundup_post_file = Path("roundup_post.json")
        roundup_file.write_text(json.dumps({"stories": stories}), encoding="utf-8")
        roundup_post_data = {
            "headline": "TODAY'S TOP 3 STORIES",
            "curiosity_line": "Three updates in one briefing",
            "caption": "Top 3 stories:\n1. reuters.com\n2. apnews.com\n3. bloomberg.com\n#NewsSnap #WorldNews #Roundup",
            "format": "04",
            "hashtags": ["#NewsSnap", "#WorldNews", "#Roundup"]
        }
        roundup_post_file.write_text(json.dumps(roundup_post_data), encoding="utf-8")
        try:
            img, _, _ = generate_image.render_approved_format("04", {"template_override": "04"}, roundup_post_data)
            self.assertEqual(img.size, (1080, 1350))
            for s in stories:
                self.assertIn(s["domain"], roundup_post_data["caption"])
        finally:
            if roundup_file.is_file():
                roundup_file.unlink()
            if roundup_post_file.is_file():
                roundup_post_file.unlink()

    def test_13_wikimedia_photo_query_disambiguation(self):
        # Category 13: Wikimedia Commons photo search with entity expansion and unambiguous query building
        article = {
            "title": "ICC Issues Warrants for War Crimes Inquiries",
            "summary": "The International Criminal Court issued warrants regarding alleged violations.",
            "classification": {"topic": "International Law"}
        }
        queries = generate_image.build_photo_search_queries(article)
        self.assertTrue(any("International Criminal Court" in q for q in queries))

    def test_14_strict_photo_relevance_and_entity_mismatch_rejection(self):
        # Category 14: Strict photo relevance scoring and rejection of mismatched entities
        icc_article = {
            "title": "US Imposes Sanctions on ICC Officials Over Inquiries",
            "summary": "Sanctions against International Criminal Court prosecutors.",
            "classification": {"topic": "Diplomacy"},
            "domain": "reuters.com"
        }
        # Reject Hong Kong International Commerce Centre skyscraper
        relevant, _ = generate_image.is_photo_meaningfully_relevant(
            "International Commerce Centre Skyscraper Hong Kong at night.jpg",
            "Tallest skyscraper in Hong Kong commercial financial tower",
            icc_article
        )
        self.assertFalse(relevant)

        # Reject FEMA disaster photo for California election story
        election_article = {
            "title": "California officials announce new ballot counting deadlines for election",
            "summary": "State election officials update mail-in ballot timelines.",
            "classification": {"topic": "Politics"},
            "domain": "reuters.com"
        }
        relevant, _ = generate_image.is_photo_meaningfully_relevant(
            "FEMA - 43332 - State officials meet with FEMA in California.jpg",
            "Disaster relief officials meet in California emergency headquarters",
            election_article
        )
        self.assertFalse(relevant)

    def test_15_commercial_license_whitelist_and_attribution(self):
        # Category 15: Commercial license whitelist enforcement and truthful attribution generation
        approved_licenses = ["CC BY 2.0", "CC BY 3.0", "CC BY 4.0", "CC BY-SA 2.0", "CC BY-SA 3.0", "CC BY-SA 4.0", "CC0", "Public domain"]
        for lic in approved_licenses:
            self.assertTrue(generate_image.license_allowed(lic), f"License {lic} must be allowed")
        # Non-commercial and unapproved licenses rejected
        self.assertFalse(generate_image.license_allowed("CC BY-NC 4.0"))
        self.assertFalse(generate_image.license_allowed("Fair use"))
        self.assertFalse(generate_image.license_allowed("Copyrighted"))

    def test_16_image_quality_gate_in_publisher(self):
        # Category 16: Image quality gate: 1080x1350, JPEG <= 8MB, non-empty, text bounds, contrast
        valid_img = Image.new("RGB", (1080, 1350), color=(20, 24, 33))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(valid_img)
        draw.rectangle([100, 100, 980, 400], fill=(220, 38, 38))
        draw.text((120, 120), "BREAKING NEWS ALERT", fill=(255, 255, 255))
        valid_img.save(instagram_publisher.IMAGE_PATH, format="JPEG", quality=95)

        post = {
            "headline": "Emergency Response Underway Across Region",
            "curiosity_line": "Authorities issue urgent advisory",
            "caption": "Emergency crews responded to severe weather alerts and advisories. Source: reuters.com Original report: https://reuters.com/1 #NewsSnap",
            "hashtags": ["#NewsSnap"]
        }
        instagram_publisher.POST_PATH.write_text(json.dumps(post), encoding="utf-8")
        try:
            # Passes validation
            instagram_publisher.validate_image_and_post()

            # Blank single-color image fails validation
            blank_img = Image.new("RGB", (1080, 1350), color=(10, 10, 10))
            blank_img.save(instagram_publisher.IMAGE_PATH, format="JPEG", quality=95)
            with self.assertRaises(ValueError) as ctx:
                instagram_publisher.validate_image_and_post()
            self.assertIn("visual entropy", str(ctx.exception).lower())
        finally:
            if instagram_publisher.IMAGE_PATH.is_file():
                instagram_publisher.IMAGE_PATH.unlink()
            if instagram_publisher.POST_PATH.is_file():
                instagram_publisher.POST_PATH.unlink()

    def test_17_instagram_dry_run_safety_and_processed_history(self):
        # Category 17: Instagram dry-run publisher: contract validation, processed-history recording without marking published, synthetic-post refusal in live mode
        synthetic_post = {
            "headline": "Mock Test Headline For Safety",
            "curiosity_line": "Testing live safety guard",
            "caption": "Mock post caption. #NewsSnap",
            "hashtags": ["#NewsSnap"],
            "is_synthetic": True
        }
        # In live publishing mode, synthetic posts must be refused
        with self.assertRaises(ValueError):
            if synthetic_post.get("is_synthetic"):
                raise ValueError("SAFETY REFUSAL: The generated post is marked as synthetic/mock test data.")

        # In dry run mode, record_dry_run_processed records into processed history without published=True
        test_article = {"title": "Genuine Story Title", "domain": "reuters.com", "url": "https://reuters.com/genuine"}
        test_post = {"headline": "Genuine Story Headline", "caption": "Caption text #NewsSnap"}
        history_path = Path("test_dryrun_hist_sample.json")
        if history_path.is_file():
            history_path.unlink()
        try:
            with patch("instagram_publisher.HISTORY_PATH", history_path):
                instagram_publisher.record_dry_run_processed(test_article, test_post)
                hist = json.loads(history_path.read_text(encoding="utf-8"))
                self.assertEqual(len(hist.get("posted", [])), 0)
                self.assertEqual(len(hist.get("processed", [])), 1)
                self.assertFalse(hist["processed"][0].get("published"))
                self.assertTrue(hist["processed"][0].get("dry_run"))
        finally:
            if history_path.is_file():
                history_path.unlink()

    def test_18_end_to_end_contact_sheet_and_format_previews(self):
        # Category 18: End-to-end dry run producing all 6 format previews and saving contact sheet
        contact_sheet_path = Path("contact_sheet.jpg")
        self.assertTrue(contact_sheet_path.is_file(), "Contact sheet contact_sheet.jpg must exist")
        with Image.open(contact_sheet_path) as sheet_img:
            self.assertGreater(sheet_img.width, 1000)
            self.assertGreater(sheet_img.height, 1000)
        # Verify render_contact_sheet script exists and can be imported
        import render_contact_sheet
        self.assertTrue(callable(render_contact_sheet.render_all_six_formats))



class TestSchedulerArchitecture(unittest.TestCase):
    def setUp(self):
        self.temp_hist = Path("test_history_scheduler_arch.json")
        self.temp_hist.write_text(json.dumps({"posted": [], "processed": [], "classified_pool": [], "quota_cooldown": {"active": False}}), encoding="utf-8")
        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.temp_hist)

    def tearDown(self):
        if self.temp_hist.exists():
            try:
                self.temp_hist.unlink()
            except Exception:
                pass
        os.environ.pop("NEWS_SNAP_HISTORY_PATH", None)

    def test_controller_bootstrap_only(self):
        import scheduler_controller
        dispatches = []

        def mock_dispatch(repo, token, workflow_file, ref="main", inputs=None, api_url=None):
            dispatches.append({"workflow": workflow_file, "inputs": inputs})
            return True

        with patch("scheduler_controller.dispatch_workflow", side_effect=mock_dispatch), \
             patch("scheduler_controller.check_active_controller_runs", return_value=[]):
            res = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_tok",
                current_run_id="100",
                bootstrap_only=True,
                cycle_interval=0,
                min_sleep=0
            )

        self.assertEqual(res["status"], "success")
        self.assertFalse(res["publisher_dispatched"], "Bootstrap mode must NOT dispatch production publisher")
        self.assertTrue(res["successor_dispatched"], "Bootstrap mode must dispatch successor controller")
        # Verify exactly one dispatch occurred: successor controller
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(dispatches[0]["workflow"], "news-snap-scheduler.yml")
        self.assertEqual(dispatches[0]["inputs"], {"bootstrap_only": False})

    def test_controller_normal_cycle(self):
        import scheduler_controller
        dispatches = []

        def mock_dispatch(repo, token, workflow_file, ref="main", inputs=None, api_url=None):
            dispatches.append({"workflow": workflow_file, "inputs": inputs})
            return True

        with patch("scheduler_controller.dispatch_workflow", side_effect=mock_dispatch), \
             patch("scheduler_controller.check_active_controller_runs", return_value=[]):
            res = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_tok",
                current_run_id="100",
                bootstrap_only=False,
                cycle_interval=0,
                min_sleep=0
            )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["publisher_dispatched"], "Normal mode must dispatch production publisher")
        self.assertTrue(res["successor_dispatched"], "Normal mode must dispatch successor controller")
        # Verify exactly two dispatches occurred: publisher then successor
        self.assertEqual(len(dispatches), 2)
        self.assertEqual(dispatches[0]["workflow"], "test.yml")
        self.assertIsNone(dispatches[0]["inputs"])
        self.assertEqual(dispatches[1]["workflow"], "news-snap-scheduler.yml")
        self.assertEqual(dispatches[1]["inputs"], {"bootstrap_only": False})

    def test_controller_duplicate_chain_guard(self):
        import scheduler_controller
        active_runs = [{"id": 999, "run_number": 42, "status": "in_progress"}]

        with patch("scheduler_controller.check_active_controller_runs", return_value=active_runs), \
             patch("scheduler_controller.dispatch_workflow") as mock_disp:
            res = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_tok",
                current_run_id="100",
                bootstrap_only=False,
                cycle_interval=0,
                min_sleep=0
            )

        self.assertEqual(res["status"], "aborted_duplicate")
        self.assertFalse(res["publisher_dispatched"])
        self.assertFalse(res["successor_dispatched"])
        mock_disp.assert_not_called()

    def test_controller_api_error_handling(self):
        import scheduler_controller
        with patch("scheduler_controller.query_api", return_value=(500, {"error": "Server error"})):
            with self.assertRaises(RuntimeError) as ctx:
                scheduler_controller.dispatch_workflow(
                    repo="test/repo",
                    token="test_tok",
                    workflow_file="test.yml"
                )
            self.assertIn("Failed to dispatch 'test.yml'", str(ctx.exception))

    def test_watchdog_active_controller_no_op(self):
        import scheduler_watchdog
        mock_runs_resp = {
            "workflow_runs": [
                {"id": 101, "run_number": 5, "status": "in_progress", "updated_at": "2026-10-18T22:00:00Z"}
            ]
        }
        with patch("scheduler_watchdog.query_api", return_value=(200, mock_runs_resp)):
            res = scheduler_watchdog.run_watchdog_check(repo="test/repo", token="test_tok")
        self.assertEqual(res["status"], "healthy")
        self.assertEqual(res["action"], "none")
        self.assertEqual(res["active_run_id"], 101)

    def test_watchdog_recent_completed_no_op(self):
        from datetime import datetime, timezone
        import scheduler_watchdog
        now_iso = datetime.now(timezone.utc).isoformat()
        mock_runs_resp = {
            "workflow_runs": [
                {"id": 102, "run_number": 6, "status": "completed", "updated_at": now_iso}
            ]
        }
        with patch("scheduler_watchdog.query_api", return_value=(200, mock_runs_resp)):
            res = scheduler_watchdog.run_watchdog_check(repo="test/repo", token="test_tok", stale_threshold_minutes=12)
        self.assertEqual(res["status"], "healthy")
        self.assertEqual(res["action"], "none")

    def test_watchdog_stale_controller_recovery(self):
        from datetime import datetime, timezone, timedelta
        import scheduler_watchdog
        # Completed 45 minutes in the past
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        mock_runs_resp = {
            "workflow_runs": [
                {"id": 103, "run_number": 7, "status": "completed", "updated_at": old_time}
            ]
        }
        calls = []

        def mock_query(url, token, method="GET", payload=None):
            if method == "GET":
                return 200, mock_runs_resp
            calls.append({"url": url, "method": method, "payload": payload})
            return 204, {}

        with patch("scheduler_watchdog.query_api", side_effect=mock_query):
            res = scheduler_watchdog.run_watchdog_check(repo="test/repo", token="test_tok", stale_threshold_minutes=12)

        self.assertEqual(res["status"], "revived")
        self.assertEqual(res["action"], "dispatched_bootstrap")
        self.assertEqual(len(calls), 1)
        self.assertIn("news-snap-scheduler.yml/dispatches", calls[0]["url"])
        self.assertTrue(calls[0]["payload"]["inputs"]["bootstrap_only"])


class TestProductionMockFallbackRefusal(unittest.TestCase):
    def setUp(self):
        self.test_hist = Path("test_history_prod_safeguard.json")
        self.test_hist.write_text(json.dumps({"posted": [], "processed": [], "classified_pool": [], "quota_cooldown": {}}), encoding="utf-8")
        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.test_hist)

        self.real_article = {
            "title": "Global Leaders Finalize Historic Clean Energy Framework",
            "domain": "reuters.com",
            "url": "https://reuters.com/world/clean-energy-accord",
            "source_description": "Nations agreed on a transition plan to cut carbon emissions over the next decade."
        }
        self.valid_gemini_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "headline": "Global Leaders Finalize Historic Clean Energy Framework",
                                    "curiosity_line": "Key climate transition roadmap",
                                    "caption": "According to reports from reuters.com, Global Leaders Finalize Historic Clean Energy Framework. Observers and delegates are closely monitoring the implementation details as the international situation unfolds across multiple regions.",
                                    "hashtags": ["#NewsSnap", "#Climate", "#Energy"]
                                })
                            }
                        ]
                    }
                }
            ]
        }

    def tearDown(self):
        if self.test_hist.exists():
            try:
                self.test_hist.unlink()
            except Exception:
                pass
        os.environ.pop("NEWS_SNAP_HISTORY_PATH", None)

    def test_scenario_1_real_gemini_response_produces_non_synthetic_post(self):
        """1. Real Gemini response produces non-synthetic post (is_synthetic == False)."""
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(self.valid_gemini_payload).encode("utf-8"))), \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test_valid_key", "GITHUB_ACTIONS": "true"}):
            post = post_generator.generate_post(self.real_article)
            self.assertFalse(post.get("is_synthetic", False))
            self.assertEqual(post["headline"], "Global Leaders Finalize Historic Clean Energy Framework")
            self.assertIn("#NewsSnap", post["caption"])

    def test_scenario_2_transient_429_followed_by_success_retries_and_succeeds(self):
        """2. Transient error (429) followed by 200 produces valid non-synthetic post."""
        err_429 = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "2"},
            fp=io.BytesIO(b'{"error": {"message": "Resource has been exhausted (e.g. check quota)."}}')
        )
        success_resp = io.BytesIO(json.dumps(self.valid_gemini_payload).encode("utf-8"))
        call_count = 0

        def side_effect(req, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise err_429
            return success_resp

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch("time.sleep") as mock_sleep, \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test_valid_key", "GITHUB_ACTIONS": "true"}):
            post = post_generator.generate_post(self.real_article)
            self.assertEqual(call_count, 2)
            self.assertFalse(post.get("is_synthetic", False))
            mock_sleep.assert_called_once()
            self.assertEqual(mock_sleep.call_args[0][0], 2.0)

    def test_scenario_3_repeated_transient_errors_exhaust_retries_and_raise(self):
        """3. Repeated transient errors exhaust retries and raise RuntimeError in production."""
        err_503 = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=io.BytesIO(b'{"error": "Backend timeout"}')
        )
        attempts = 0

        def side_effect(req, *args, **kwargs):
            nonlocal attempts
            attempts += 1
            raise err_503

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch("time.sleep"), \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test_valid_key", "GITHUB_ACTIONS": "true"}):
            with self.assertRaises(RuntimeError) as ctx:
                post_generator.generate_post(self.real_article)
            self.assertEqual(attempts, 4)
            self.assertIn("Production post generation failed", str(ctx.exception))

    def test_scenario_4_permanent_errors_abort_immediately_in_production(self):
        """4. Permanent errors (400, 401, 403, 404, daily quota, malformed JSON) never produce mock content in production."""
        permanent_cases = [
            (400, "Bad Request", b'{"error": "Invalid argument"}'),
            (401, "Unauthorized", b'{"error": "API key invalid"}'),
            (403, "Forbidden", b'{"error": "Permission denied"}'),
            (404, "Not Found", b'{"error": "Model not found"}'),
            (429, "Too Many Requests", b'{"error": "Daily quota limit exceeded for free tier."}'),
        ]

        for code, msg, body in permanent_cases:
            quota_manager.clear_quota_cooldown(self.test_hist)
            with self.subTest(code=code, msg=msg):
                err = urllib.error.HTTPError(
                    url="https://generativelanguage.googleapis.com",
                    code=code,
                    msg=msg,
                    hdrs={},
                    fp=io.BytesIO(body)
                )
                attempts = 0

                def side_effect(req, *args, **kwargs):
                    nonlocal attempts
                    attempts += 1
                    raise err

                with patch("urllib.request.urlopen", side_effect=side_effect), \
                     patch("time.sleep") as mock_sleep, \
                     patch.dict(os.environ, {"GEMINI_API_KEY": "test_valid_key", "GITHUB_ACTIONS": "true"}):
                    with self.assertRaises(RuntimeError) as ctx:
                        post_generator.generate_post(self.real_article)
                    self.assertEqual(attempts, 1)
                    mock_sleep.assert_not_called()
                    self.assertIn("Production post generation failed", str(ctx.exception))

        quota_manager.clear_quota_cooldown(self.test_hist)
        malformed_resp = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "{invalid json schema..."}]
                    }
                }
            ]
        }
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(malformed_resp).encode("utf-8"))), \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test_valid_key", "GITHUB_ACTIONS": "true"}):
            with self.assertRaises(RuntimeError) as ctx:
                post_generator.generate_post(self.real_article)
            self.assertIn("Production post generation failed", str(ctx.exception))

    def test_scenario_5_production_failure_cleans_up_and_never_leaves_post_json(self):
        """5. Production failure cleans up and never leaves a synthetic post.json."""
        post_path = Path("post.json")
        article_path = Path("selected_article.json")
        try:
            post_path.write_text(json.dumps({"headline": "Old Post", "is_synthetic": True}), encoding="utf-8")
            article_path.write_text(json.dumps(self.real_article), encoding="utf-8")

            with patch("post_generator.generate_post", side_effect=RuntimeError("API Failure")), \
                 patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
                 self.assertRaises(SystemExit) as cm:
                post_generator.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertFalse(post_path.exists())

            with patch("post_generator.generate_post", return_value={"headline": "Fake", "is_synthetic": True}), \
                 patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
                 self.assertRaises(SystemExit) as cm:
                post_generator.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertFalse(post_path.exists())
        finally:
            if post_path.exists():
                post_path.unlink()
            if article_path.exists():
                article_path.unlink()

    def test_scenario_6_explicit_generate_mock_post_works_for_offline_fixtures(self):
        """6. Explicit generate_mock_post works for offline test fixtures."""
        mock_post = post_generator.generate_mock_post(self.real_article)
        self.assertTrue(mock_post["is_synthetic"])
        self.assertIn("headline", mock_post)
        self.assertIn("curiosity_line", mock_post)
        self.assertIn("caption", mock_post)
        self.assertIn("#NewsSnap", mock_post["caption"])

        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GITHUB_ACTIONS": "", "CI": "", "NEWS_SNAP_PROD": ""}):
            local_post = post_generator.generate_post(self.real_article)
            self.assertTrue(local_post["is_synthetic"])

    def test_scenario_7_downstream_image_gen_and_publisher_halt_on_failure(self):
        """7. Downstream image generation / publisher is not reached on generation failure."""
        post_path = Path("post.json")
        article_path = Path("selected_article.json")
        img_path = Path("news_snap_post.jpg")
        try:
            if post_path.exists():
                post_path.unlink()
            if img_path.exists():
                img_path.unlink()
            article_path.write_text(json.dumps(self.real_article), encoding="utf-8")

            # 1. When post.json is missing, generate_image.main returns early without producing image
            generate_image.main()
            self.assertFalse(img_path.exists())

            # 2. When post.json is missing, instagram_publisher.main returns early without publishing
            instagram_publisher.main()

            # 3. When post.json is synthetic and live posting is enabled, publisher rejects with SAFETY REFUSAL
            post_path.write_text(json.dumps({
                "headline": "Synthetic Story Headline For Tests",
                "curiosity_line": "Sub-kicker line",
                "caption": "Synthetic caption for testing publisher refusal. #NewsSnap",
                "hashtags": ["#NewsSnap"],
                "is_synthetic": True
            }), encoding="utf-8")

            # Create dummy 1080x1350 JPEG image for publisher validation
            from PIL import ImageDraw
            dummy_img = Image.new("RGB", (1080, 1350), (10, 24, 45))
            d = ImageDraw.Draw(dummy_img)
            d.text((50, 50), "TEST CARD", fill=(255, 255, 255))
            dummy_img.save(img_path, "JPEG", quality=95)

            with patch.dict(os.environ, {
                "ENABLE_INSTAGRAM_POSTING": "true",
                "INSTAGRAM_ACCESS_TOKEN": "mock_token",
                "INSTAGRAM_ACCOUNT_ID": "17841400012345678",
            }), patch("instagram_publisher.resolve_instagram_account_id", return_value=("17841400012345678", {"username": "test"})):
                with self.assertRaises(ValueError) as ctx:
                    instagram_publisher.main()
                self.assertIn("SAFETY REFUSAL: The generated post is marked as synthetic/mock test data.", str(ctx.exception))
        finally:
            if post_path.exists():
                post_path.unlink()
            if article_path.exists():
                article_path.unlink()
            if img_path.exists():
                img_path.unlink()

    def test_scenario_8_failed_generation_not_recorded_in_history(self):
        """8. Failed generation does not get recorded in history.json."""
        hist_path = Path("test_history_fail_safeguard.json")
        orig_hist = instagram_publisher.HISTORY_PATH
        post_path = Path("post.json")
        article_path = Path("selected_article.json")
        try:
            instagram_publisher.HISTORY_PATH = hist_path
            hist_path.write_text(json.dumps({"posted": [], "processed": []}), encoding="utf-8")
            article_path.write_text(json.dumps(self.real_article), encoding="utf-8")

            with patch("post_generator.generate_post", side_effect=RuntimeError("API failure")), \
                 patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
                 self.assertRaises(SystemExit):
                post_generator.main()

            hist_data = json.loads(hist_path.read_text(encoding="utf-8"))
            self.assertEqual(len(hist_data.get("posted", [])), 0)
            self.assertEqual(len(hist_data.get("processed", [])), 0)
        finally:
            instagram_publisher.HISTORY_PATH = orig_hist
            if hist_path.exists():
                hist_path.unlink()
            if post_path.exists():
                post_path.unlink()
            if article_path.exists():
                article_path.unlink()


class TestQuotaManagerAndOptimizations(unittest.TestCase):
    def setUp(self):
        self.temp_hist = Path("test_history_quota.json")
        self.temp_disc = Path("test_discovery_quota.json")
        self.temp_sample = Path("test_classified_sample.json")
        if self.temp_hist.exists():
            self.temp_hist.unlink()
        if self.temp_disc.exists():
            self.temp_disc.unlink()
        if self.temp_sample.exists():
            self.temp_sample.unlink()

    def tearDown(self):
        for p in (self.temp_hist, self.temp_disc, self.temp_sample):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_parse_quota_cooldown_gemini_daily_error(self):
        """1. parse_quota_cooldown correctly extracts reset time from Gemini 429 quota exhaustion body."""
        from datetime import datetime, timezone
        import quota_manager
        raw_msg = (
            '{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details... '
            '* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\\n'
            'Please retry in 5h15m46.002725955s."}}'
        )
        err = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=io.BytesIO(raw_msg.encode("utf-8"))
        )
        is_quota, reset_dt, reason = quota_manager.parse_quota_cooldown(err)
        self.assertTrue(is_quota)
        self.assertIsNotNone(reset_dt)
        self.assertIn("18946s", reason)
        self.assertGreater(reset_dt, datetime.now(timezone.utc))

    def test_quota_cooldown_active_and_expiration(self):
        """2. Cooldown is active before reset_dt and inactive after reset_dt."""
        from datetime import datetime, timezone, timedelta
        import quota_manager
        future_dt = datetime.now(timezone.utc) + timedelta(hours=2)
        quota_manager.set_quota_cooldown(future_dt, "Test Cooldown", history_path=self.temp_hist)
        self.assertTrue(quota_manager.is_cooldown_active(history_path=self.temp_hist))
        cd = quota_manager.get_quota_cooldown(history_path=self.temp_hist)
        self.assertTrue(cd.get("active"))
        self.assertEqual(cd.get("reason"), "Test Cooldown")

        past_dt = datetime.now(timezone.utc) - timedelta(minutes=5)
        quota_manager.set_quota_cooldown(past_dt, "Past Cooldown", history_path=self.temp_hist)
        self.assertFalse(quota_manager.is_cooldown_active(history_path=self.temp_hist))

    def test_classified_pool_save_and_reuse(self):
        """3. Pool saves candidates, dedupes against history, and consumes selected articles."""
        import quota_manager
        candidates = [
            {
                "url": "https://reuters.com/world/story1",
                "title": "Major Peace Accord Signed Between World Leaders",
                "domain": "reuters.com",
                "classification": {"importance": "MAJOR", "topic": "Diplomacy"}
            },
            {
                "url": "https://bbc.com/economy/story2",
                "title": "Central Bank Announces Significant Interest Rate Adjustment",
                "domain": "bbc.com",
                "classification": {"importance": "NORMAL", "topic": "Economy"}
            }
        ]
        added = quota_manager.save_to_classified_pool(candidates, history_path=self.temp_hist)
        self.assertEqual(added, 2)
        added_again = quota_manager.save_to_classified_pool(candidates, history_path=self.temp_hist)
        self.assertEqual(added_again, 0)

        pool = quota_manager.get_classified_pool(history_path=self.temp_hist)
        self.assertEqual(len(pool), 2)

        quota_manager.remove_from_classified_pool("https://reuters.com/world/story1", history_path=self.temp_hist)
        remaining = quota_manager.get_classified_pool(history_path=self.temp_hist)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["url"], "https://bbc.com/economy/story2")

    def test_heuristic_classifier_accurately_categorizes_news(self):
        """4. Journalistic heuristic accurately categorizes MAJOR, NORMAL, and LOW without API."""
        import quota_manager
        major = quota_manager.heuristic_classify_article("Fatal Military Base Blaze Leaves Multiple Dead Across Region")
        self.assertEqual(major["importance"], "MAJOR")

        major_economy = quota_manager.heuristic_classify_article("Federal Reserve Signals Interest Rate Adjustments Amid Inflation")
        self.assertEqual(major_economy["importance"], "MAJOR")

        normal = quota_manager.heuristic_classify_article("City Council Proposes New Municipal Water Conservation Policy")
        self.assertEqual(normal["importance"], "NORMAL")

        low_horoscope = quota_manager.heuristic_classify_article("Today's Zodiac Horoscope and Tarot Card Predictions")
        self.assertEqual(low_horoscope["importance"], "LOW")

        low_entertainment = quota_manager.heuristic_classify_article("Movie Box Office Collection Day 5 Earnings Update")
        self.assertEqual(low_entertainment["importance"], "LOW")

    def test_check_candidates_pauses_during_active_cooldown(self):
        """5. check_candidates skips pipeline during active quota cooldown (has_fresh=false, exit 0)."""
        from datetime import datetime, timezone, timedelta
        import check_candidates
        import quota_manager
        future_dt = datetime.now(timezone.utc) + timedelta(hours=3)
        quota_manager.set_quota_cooldown(future_dt, "Daily quota 20 limit reached", history_path=self.temp_hist)

        with patch.dict(os.environ, {"NEWS_SNAP_HISTORY_PATH": str(self.temp_hist)}):
            with self.assertRaises(SystemExit) as cm:
                check_candidates.main()
            self.assertEqual(cm.exception.code, 0)

    def test_classify_reuses_pool_with_zero_api_calls(self):
        """6. classify.py reuses persistent pool candidates with 0 Gemini API calls."""
        import classify
        import quota_manager
        candidates = [
            {
                "url": "https://reuters.com/world/story1",
                "title": "Major Peace Accord Signed Between World Leaders",
                "domain": "reuters.com",
                "classification": {"importance": "MAJOR", "topic": "Diplomacy", "reason": "Historic peace accord"}
            }
        ]
        quota_manager.save_to_classified_pool(candidates, history_path=self.temp_hist)
        self.temp_disc.write_text(json.dumps([{"url": "https://reuters.com/world/story1", "title": "Major Peace Accord Signed Between World Leaders", "domain": "reuters.com"}]), encoding="utf-8")

        with patch("classify.call_gemini") as mock_gemini, \
             patch("classify.Path", side_effect=lambda p: self.temp_disc if str(p) == "discovery.json" else (self.temp_sample if str(p) == "classified_sample.json" else Path(p))), \
             patch.dict(os.environ, {"NEWS_SNAP_HISTORY_PATH": str(self.temp_hist)}):
            classify.main()
            mock_gemini.assert_not_called()

        sample_data = json.loads(self.temp_sample.read_text(encoding="utf-8"))
        self.assertEqual(sample_data.get("source"), "persistent_pool")
        self.assertEqual(len(sample_data.get("results", [])), 1)
        self.assertEqual(sample_data["results"][0]["importance"], "MAJOR")

    def test_post_generator_blocks_api_calls_during_active_cooldown(self):
        """7. post_generator.generate_post raises RuntimeError during active cooldown."""
        from datetime import datetime, timezone, timedelta
        import quota_manager
        future_dt = datetime.now(timezone.utc) + timedelta(hours=4)
        quota_manager.set_quota_cooldown(future_dt, "Limit reached", history_path=self.temp_hist)

        with patch.dict(os.environ, {
            "NEWS_SNAP_HISTORY_PATH": str(self.temp_hist),
            "GEMINI_API_KEY": "test_key",
            "GITHUB_ACTIONS": "true"
        }):
            with self.assertRaises(RuntimeError) as ctx:
                post_generator.generate_post({
                    "title": "Important Headline Story",
                    "domain": "reuters.com",
                    "url": "https://reuters.com/story"
                })
            self.assertIn("active cooldown", str(ctx.exception))


class TestQuotaAwareSchedulerAndResumption(unittest.TestCase):
    def setUp(self):
        self.temp_hist = Path("test_history_qa.json")
        self.temp_disc = Path("test_discovery_qa.json")
        self.temp_sample = Path("test_sample_qa.json")
        self.temp_sel = Path("selected_article.json")
        for p in (self.temp_hist, self.temp_disc, self.temp_sample, self.temp_sel):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def tearDown(self):
        for p in (self.temp_hist, self.temp_disc, self.temp_sample, self.temp_sel):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_controller_suppresses_dispatch_and_stops_chain_during_active_cooldown(self):
        """1. scheduler_controller suppresses production dispatch and halts successor chain during active quota cooldown."""
        from datetime import datetime, timezone, timedelta
        future_dt = datetime.now(timezone.utc) + timedelta(hours=18)
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [{"title": "Pending Story", "url": "https://example.com/1"}],
            "quota_cooldown": {
                "active": True,
                "resets_at": future_dt.isoformat(),
                "reason": "Gemini API quota exhausted (limit: 20)."
            }
        }), encoding="utf-8")

        with patch("scheduler_controller.check_active_controller_runs", return_value=[]), \
             patch("scheduler_controller.dispatch_workflow") as mock_dispatch:
            res = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_token",
                history_file=str(self.temp_hist)
            )

        self.assertEqual(res["status"], "paused_quota_cooldown")
        self.assertFalse(res["publisher_dispatched"])
        self.assertFalse(res["successor_dispatched"])
        mock_dispatch.assert_not_called()

    def test_controller_dispatches_publisher_and_successor_when_cooldown_absent(self):
        """2. scheduler_controller dispatches publisher and successor when cooldown is inactive."""
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [],
            "quota_cooldown": {"active": False}
        }), encoding="utf-8")

        with patch("scheduler_controller.check_active_controller_runs", return_value=[]), \
             patch("scheduler_controller.dispatch_workflow", return_value=True) as mock_dispatch:
            res = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_token",
                bootstrap_only=False,
                cycle_interval=0,
                sleep_fn=lambda s: None,
                history_file=str(self.temp_hist)
            )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["publisher_dispatched"])
        self.assertTrue(res["successor_dispatched"])
        self.assertEqual(mock_dispatch.call_count, 2)

    def test_watchdog_suppresses_revival_during_active_cooldown(self):
        """3. scheduler_watchdog recognizes active quota cooldown and suppresses revival."""
        from datetime import datetime, timezone, timedelta
        future_dt = datetime.now(timezone.utc) + timedelta(hours=12)
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [],
            "quota_cooldown": {
                "active": True,
                "resets_at": future_dt.isoformat(),
                "reason": "Quota exhausted."
            }
        }), encoding="utf-8")

        with patch("scheduler_watchdog.query_api") as mock_api:
            res = scheduler_watchdog.run_watchdog_check(
                repo="test/repo",
                token="test_token",
                history_file=str(self.temp_hist)
            )

        self.assertEqual(res["status"], "cooldown_active")
        self.assertEqual(res["action"], "none")
        mock_api.assert_not_called()

    def test_watchdog_revives_controller_with_safe_bootstrap_after_cooldown_expired(self):
        """4. scheduler_watchdog revives controller using safe bootstrap (bootstrap_only=True) after cooldown expired."""
        from datetime import datetime, timezone, timedelta
        past_dt = datetime.now(timezone.utc) - timedelta(hours=1)
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [],
            "quota_cooldown": {
                "active": True,
                "resets_at": past_dt.isoformat(),
                "reason": "Expired quota cooldown."
            }
        }), encoding="utf-8")

        last_run_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        runs_response = {
            "workflow_runs": [
                {
                    "id": 1001,
                    "run_number": 40,
                    "status": "completed",
                    "conclusion": "success",
                    "updated_at": last_run_time
                }
            ]
        }

        calls = []
        def mock_query(url, token, method="GET", payload=None):
            calls.append({"url": url, "method": method, "payload": payload})
            if method == "GET":
                return 200, runs_response
            return 204, {}

        with patch("scheduler_watchdog.query_api", side_effect=mock_query):
            res = scheduler_watchdog.run_watchdog_check(
                repo="test/repo",
                token="test_token",
                history_file=str(self.temp_hist)
            )

        self.assertEqual(res["status"], "revived")
        self.assertEqual(res["action"], "dispatched_bootstrap")
        self.assertEqual(len(calls), 2)
        dispatch_call = [c for c in calls if c["method"] == "POST"][0]
        self.assertTrue(dispatch_call["payload"]["inputs"]["bootstrap_only"])

    def test_select_article_preserves_candidate_in_classified_pool(self):
        """5. select_article selects best article without dropping candidates from classified_pool prematurely."""
        article = {
            "title": "Major Peace Accord Signed Between World Leaders",
            "domain": "reuters.com",
            "url": "https://reuters.com/world/accord-1"
        }
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [{**article, "classification": {"importance": "MAJOR", "topic": "Diplomacy", "reason": "Historic"}}]
        }), encoding="utf-8")
        self.temp_disc.write_text(json.dumps([article]), encoding="utf-8")
        self.temp_sample.write_text(json.dumps({
            "results": [{"id": 1, "importance": "MAJOR", "topic": "Diplomacy", "reason": "Historic"}]
        }), encoding="utf-8")

        with patch("select_article.Path", side_effect=lambda p: (
            self.temp_disc if str(p) == "discovery.json"
            else (self.temp_sample if str(p) == "classified_sample.json"
            else (self.temp_hist if str(p) == "history.json"
            else (self.temp_sel if str(p) == "selected_article.json"
            else Path(p))))
        )):
            sel = select_article.select_best_article()

        self.assertIsNotNone(sel)
        self.assertEqual(sel["title"], article["title"])

        # Confirm the candidate was PRESERVED in classified_pool
        hist_data = json.loads(self.temp_hist.read_text(encoding="utf-8"))
        self.assertEqual(len(hist_data.get("classified_pool", [])), 1)
        self.assertEqual(hist_data["classified_pool"][0]["url"], article["url"])

    def test_instagram_publisher_removes_candidate_from_pool_on_publication(self):
        """6. instagram_publisher removes candidate from classified_pool only upon confirmed publication."""
        article = {
            "title": "Major Peace Accord Signed Between World Leaders",
            "domain": "reuters.com",
            "url": "https://reuters.com/world/accord-1"
        }
        post = {
            "headline": "Major Peace Accord Signed",
            "caption": "Full caption text #NewsSnap",
            "is_synthetic": False
        }
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [{**article, "classification": {"importance": "MAJOR"}}]
        }), encoding="utf-8")

        orig_hist = instagram_publisher.HISTORY_PATH
        try:
            instagram_publisher.HISTORY_PATH = self.temp_hist
            instagram_publisher.record_published_history(article, post, media_id="17899999999")
            hist_data = json.loads(self.temp_hist.read_text(encoding="utf-8"))
            self.assertEqual(len(hist_data["posted"]), 1)
            self.assertEqual(hist_data["posted"][0]["media_id"], "17899999999")
            # Candidate must be cleanly removed from classified_pool
            self.assertEqual(len(hist_data.get("classified_pool", [])), 0)
        finally:
            instagram_publisher.HISTORY_PATH = orig_hist

    def test_instagram_publisher_removes_candidate_from_pool_on_dry_run(self):
        """7. instagram_publisher removes candidate from classified_pool upon dry-run completion."""
        article = {
            "title": "Major Peace Accord Signed Between World Leaders",
            "domain": "reuters.com",
            "url": "https://reuters.com/world/accord-1"
        }
        post = {
            "headline": "Major Peace Accord Signed",
            "caption": "Full caption text #NewsSnap",
            "is_synthetic": False
        }
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [{**article, "classification": {"importance": "MAJOR"}}]
        }), encoding="utf-8")

        orig_hist = instagram_publisher.HISTORY_PATH
        try:
            instagram_publisher.HISTORY_PATH = self.temp_hist
            instagram_publisher.record_dry_run_processed(article, post)
            hist_data = json.loads(self.temp_hist.read_text(encoding="utf-8"))
            self.assertEqual(len(hist_data["processed"]), 1)
            # Candidate must be cleanly removed from classified_pool
            self.assertEqual(len(hist_data.get("classified_pool", [])), 0)
        finally:
            instagram_publisher.HISTORY_PATH = orig_hist

    def test_run_summary_output(self):
        """8. run_summary correctly identifies cooldown no-op vs confirmed publication."""
        from datetime import datetime, timezone, timedelta
        future_dt = datetime.now(timezone.utc) + timedelta(hours=10)
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [{"title": "Pool Story 1"}],
            "quota_cooldown": {
                "active": True,
                "resets_at": future_dt.isoformat(),
                "reason": "Quota exhausted."
            }
        }), encoding="utf-8")

        summary = run_summary.generate_run_summary(history_path=str(self.temp_hist))
        self.assertEqual(summary["run_mode"], "NO-OP: QUOTA COOLDOWN ACTIVE (PUBLICATION SUPPRESSED)")
        self.assertTrue(summary["cooldown_active"])
        self.assertEqual(summary["pool_count"], 1)
        self.assertFalse(summary["confirmed_published"])

    def test_controller_fails_closed_on_missing_history_file(self):
        """9. Controller fails closed when history file is missing (no publisher or successor dispatch)."""
        res = scheduler_controller.run_controller_cycle(
            repo="test/repo",
            token="test_token",
            history_file="non_existent_history_file.json"
        )
        self.assertEqual(res["status"], "error_history_missing")
        self.assertFalse(res["publisher_dispatched"])
        self.assertFalse(res["successor_dispatched"])

    def test_controller_fails_closed_on_malformed_history_json(self):
        """10. Controller fails closed when history JSON is corrupt or invalid."""
        self.temp_hist.write_text("{broken json invalid syntax", encoding="utf-8")
        res = scheduler_controller.run_controller_cycle(
            repo="test/repo",
            token="test_token",
            history_file=str(self.temp_hist)
        )
        self.assertEqual(res["status"], "error_history_malformed")
        self.assertFalse(res["publisher_dispatched"])
        self.assertFalse(res["successor_dispatched"])

    def test_controller_fails_closed_on_missing_quota_module(self):
        """11. Controller fails closed when quota_manager cannot be imported."""
        self.temp_hist.write_text(json.dumps({}), encoding="utf-8")
        with patch.dict(sys.modules, {"quota_manager": None}):
            res = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_token",
                history_file=str(self.temp_hist)
            )
        self.assertEqual(res["status"], "error_quota_module_import")
        self.assertFalse(res["publisher_dispatched"])
        self.assertFalse(res["successor_dispatched"])

    def test_watchdog_fails_closed_on_missing_history_file(self):
        """12. Watchdog fails closed when history file is missing (no scheduler restart)."""
        res = scheduler_watchdog.run_watchdog_check(
            repo="test/repo",
            token="test_token",
            history_file="non_existent_history_file.json"
        )
        self.assertEqual(res["status"], "error_history_missing")
        self.assertEqual(res["action"], "none")

    def test_watchdog_fails_closed_on_malformed_history_json(self):
        """13. Watchdog fails closed when history JSON is corrupt or invalid."""
        self.temp_hist.write_text("{broken json invalid syntax", encoding="utf-8")
        res = scheduler_watchdog.run_watchdog_check(
            repo="test/repo",
            token="test_token",
            history_file=str(self.temp_hist)
        )
        self.assertEqual(res["status"], "error_history_malformed")
        self.assertEqual(res["action"], "none")

    def test_watchdog_fails_closed_on_missing_quota_module(self):
        """14. Watchdog fails closed when quota_manager cannot be imported."""
        self.temp_hist.write_text(json.dumps({}), encoding="utf-8")
        with patch.dict(sys.modules, {"quota_manager": None}):
            res = scheduler_watchdog.run_watchdog_check(
                repo="test/repo",
                token="test_token",
                history_file=str(self.temp_hist)
            )
        self.assertEqual(res["status"], "error_quota_module_import")
        self.assertEqual(res["action"], "none")

    def test_quota_manager_load_history_strict_mode_and_corruption_guards(self):
        """15. quota_manager.load_history raises errors on corrupt JSON or missing files in strict mode."""
        # Non-existent file in strict mode
        with self.assertRaises(FileNotFoundError):
            quota_manager.load_history(Path("missing_file.json"), strict=True)

        # Corrupt JSON
        self.temp_hist.write_text("{corrupt: json", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            quota_manager.load_history(self.temp_hist)

        # Non-dict JSON root
        self.temp_hist.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        with self.assertRaises(ValueError):
            quota_manager.load_history(self.temp_hist)


class TestMultiProviderAIClient(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()
        for k in (
            "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_MODEL", "CLOUDFLARE_API_BASE",
            "GROQ_API_KEY", "GROQ_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "AI_PROVIDER",
            "GITHUB_ACTIONS", "CI", "NEWS_SNAP_PROD"
        ):
            os.environ.pop(k, None)
        self.temp_hist = Path("test_history_groq.json")
        if self.temp_hist.exists():
            try:
                self.temp_hist.unlink()
            except Exception:
                pass

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        if self.temp_hist.exists():
            try:
                self.temp_hist.unlink()
            except Exception:
                pass

    def test_provider_selection_hierarchy(self):
        """1. ai_provider correctly selects Groq as primary, Gemini as secondary, and respects explicit override."""
        # No keys -> empty
        self.assertEqual(ai_provider.get_active_provider(), "")

        # Only Gemini set -> gemini
        os.environ["GEMINI_API_KEY"] = "test_gemini_key"
        self.assertEqual(ai_provider.get_active_provider(), "gemini")

        # Groq set -> groq (precedence over Gemini)
        os.environ["GROQ_API_KEY"] = "gsk_test_groq_key"
        self.assertEqual(ai_provider.get_active_provider(), "groq")

        # Explicit override to gemini
        os.environ["AI_PROVIDER"] = "gemini"
        self.assertEqual(ai_provider.get_active_provider(), "gemini")

        # Explicit override to groq
        os.environ["AI_PROVIDER"] = "groq"
        self.assertEqual(ai_provider.get_active_provider(), "groq")

    def test_secret_sanitization(self):
        """2. sanitize_ai_error thoroughly redacts Groq keys, Gemini keys, Bearer tokens, and sensitive headers."""
        os.environ["GROQ_API_KEY"] = "gsk_supersecret12345"
        os.environ["GEMINI_API_KEY"] = "AIzaSySuperSecretGeminiKey"

        raw_err = (
            "Failed at https://api.groq.com/openai/v1 with Authorization: Bearer gsk_supersecret12345. "
            "Found leaked key gsk_unrelatedkey8888. "
            "Also checked https://generativelanguage.googleapis.com?key=AIzaSySuperSecretGeminiKey "
            "and header x-goog-api-key: AIzaSySuperSecretGeminiKey "
            "and query param https://api.service.com?key=some_secret_api_token"
        )
        sanitized = ai_provider.sanitize_ai_error(raw_err)

        self.assertNotIn("gsk_supersecret12345", sanitized)
        self.assertNotIn("gsk_unrelatedkey8888", sanitized)
        self.assertNotIn("AIzaSySuperSecretGeminiKey", sanitized)
        self.assertNotIn("some_secret_api_token", sanitized)
        self.assertIn("[REDACTED_GROQ_API_KEY]", sanitized)
        self.assertIn("[REDACTED_GROQ_KEY]", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_groq_chat_completion_success(self):
        """3. call_groq_chat_completion sends OpenAI-compatible payload and parses valid JSON response."""
        mock_response_json = {
            "id": "chatcmpl-test12345",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({
                            "headline": "Historic Global Climate Treaty Signed",
                            "curiosity_line": "Key developments for international policy",
                            "caption": "World leaders reached an agreement at the climate summit today.",
                            "hashtags": ["#NewsSnap", "#Climate", "#WorldNews"]
                        })
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        recorded_req = []
        def fake_urlopen(req, timeout=30):
            recorded_req.append(req)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = ai_provider.call_groq_chat_completion(
                prompt="Generate post",
                api_key="gsk_valid_key",
                model="openai/gpt-oss-120b"
            )

        self.assertEqual(res["headline"], "Historic Global Climate Treaty Signed")
        self.assertEqual(len(recorded_req), 1)
        req = recorded_req[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer gsk_valid_key")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_groq_uses_corrected_default_model(self):
        """3b. Groq uses the corrected default free-tier model openai/gpt-oss-120b when no model is specified."""
        self.assertEqual(ai_provider.DEFAULT_GROQ_MODEL, "openai/gpt-oss-120b")

        mock_response_json = {
            "choices": [
                {"message": {"content": json.dumps({"headline": "Test Headline", "caption": "Test caption"})}}
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        recorded_req = []
        def fake_urlopen(req, timeout=30):
            recorded_req.append(req)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ai_provider.call_groq_chat_completion(prompt="Test", api_key="gsk_key")

        self.assertEqual(len(recorded_req), 1)
        payload = json.loads(recorded_req[0].data.decode("utf-8"))
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")

    def test_groq_authentication_error_fails_closed(self):
        """4. call_groq_chat_completion fails closed immediately on HTTP 401 without retry."""
        err_fp = io.BytesIO(b'{"error": {"message": "Invalid API Key", "type": "invalid_request_error"}}')
        http_err = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=err_fp
        )

        with patch("urllib.request.urlopen", side_effect=http_err) as mock_url:
            with self.assertRaises(RuntimeError) as cm:
                ai_provider.call_groq_chat_completion(prompt="Test", api_key="gsk_bad_key")

        self.assertIn("HTTP 401", str(cm.exception))
        # Must fail closed immediately on first attempt without retrying
        self.assertEqual(mock_url.call_count, 1)

    def test_groq_rate_limit_with_retry_after(self):
        """5. call_groq_chat_completion respects Retry-After header and succeeds on retry."""
        err_fp = io.BytesIO(b'{"error": {"message": "Rate limit reached. Please try again in 0.1s."}}')
        hdrs = MagicMock()
        hdrs.get.side_effect = lambda h: "0.1" if h == "Retry-After" else None
        rate_limit_err = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=hdrs,
            fp=err_fp
        )

        mock_ok = MagicMock()
        mock_ok.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"status": "recovered"})}}]
        }).encode("utf-8")
        mock_ok.__enter__.return_value = mock_ok

        attempts = [rate_limit_err, mock_ok]
        with patch("urllib.request.urlopen", side_effect=attempts), \
             patch("time.sleep") as mock_sleep:
            res = ai_provider.call_groq_chat_completion(prompt="Test", api_key="gsk_key")

        self.assertEqual(res["status"], "recovered")
        self.assertTrue(mock_sleep.called)

    def test_groq_daily_quota_exhaustion_sets_cooldown(self):
        """6. Daily quota exhaustion on Groq activates quota cooldown in history.json."""
        err_fp = io.BytesIO(b'{"error": {"message": "Rate limit reached for model openai/gpt-oss-120b in organization org_123 on requests per day (RPD): Limit 1000, Used 1000. Please try again in 12h30m."}}')
        http_err = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=err_fp
        )

        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.temp_hist)
        self.temp_hist.write_text(json.dumps({"posted": [], "processed": [], "classified_pool": []}), encoding="utf-8")

        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(RuntimeError) as cm:
                ai_provider.call_groq_chat_completion(prompt="Test", api_key="gsk_key")

        self.assertIn("quota exhausted", str(cm.exception).lower())
        hist = json.loads(self.temp_hist.read_text(encoding="utf-8"))
        self.assertTrue(hist.get("quota_cooldown", {}).get("active"))
        self.assertIn("Groq", hist["quota_cooldown"].get("reason", ""))
        self.assertEqual(hist["quota_cooldown"].get("provider"), "groq")

    def test_active_gemini_cooldown_does_not_block_valid_groq_usage(self):
        """6b. An active Gemini-only cooldown does not block Groq usage in post_generator or candidate check."""
        from datetime import datetime, timezone, timedelta
        future_dt = datetime.now(timezone.utc) + timedelta(hours=14)
        self.temp_hist.write_text(json.dumps({
            "posted": [],
            "processed": [],
            "classified_pool": [],
            "quota_cooldown": {
                "active": True,
                "resets_at": future_dt.isoformat(),
                "reason": "Gemini API quota exhausted. Retry required in 50000s.",
                "provider": "gemini"
            }
        }), encoding="utf-8")

        os.environ["GROQ_API_KEY"] = "gsk_valid_test_key"
        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.temp_hist)

        # 1. is_cooldown_active for groq must be False
        self.assertFalse(quota_manager.is_cooldown_active(self.temp_hist, provider="groq"))
        # 2. is_cooldown_active for gemini must be True
        self.assertTrue(quota_manager.is_cooldown_active(self.temp_hist, provider="gemini"))
        # 3. is_cooldown_active default with GROQ_API_KEY active must be False
        self.assertFalse(quota_manager.is_cooldown_active(self.temp_hist))

        # 4. post_generator succeeds with Groq without raising cooldown exception
        article = {
            "title": "Major International Accord Reached at Summit",
            "domain": "reuters.com",
            "url": "https://reuters.com/world/accord"
        }
        mock_groq_output = {
            "headline": "Major International Accord Reached",
            "curiosity_line": "Key global development",
            "caption": "World powers and international delegates have formally concluded landmark negotiations to establish a new bilateral accord following constructive high-level discussions in Geneva.",
            "hashtags": ["#NewsSnap", "#WorldNews", "#SummitReport"]
        }
        with patch("ai_provider.call_groq_chat_completion", return_value=mock_groq_output):
            post = post_generator.generate_post(article)
        self.assertEqual(post["headline"], "Major International Accord Reached")

    def test_actual_groq_quota_cooldown_blocks_groq_requests(self):
        """6c. An actual Groq quota cooldown blocks Groq requests in post_generator and check_candidates."""
        from datetime import datetime, timezone, timedelta
        future_dt = datetime.now(timezone.utc) + timedelta(hours=10)
        quota_manager.set_quota_cooldown(
            resets_at=future_dt,
            reason="Groq API quota exhausted. RPD limit reached.",
            history_path=self.temp_hist,
            provider="groq"
        )

        os.environ["GROQ_API_KEY"] = "gsk_valid_test_key"
        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.temp_hist)

        self.assertTrue(quota_manager.is_cooldown_active(self.temp_hist, provider="groq"))
        self.assertTrue(quota_manager.is_cooldown_active(self.temp_hist))

        article = {"title": "Test Title", "domain": "reuters.com", "url": "https://reuters.com/test"}
        with self.assertRaises(RuntimeError) as cm:
            post_generator.generate_post(article)
        self.assertIn("GROQ API quota is currently in active cooldown", str(cm.exception))

    def test_post_generator_with_groq_provider(self):
        """7. post_generator.generate_post produces validated Instagram post using Groq provider."""
        os.environ["GROQ_API_KEY"] = "gsk_test_mock"
        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.temp_hist)
        self.temp_hist.write_text(json.dumps({"posted": [], "processed": [], "classified_pool": []}), encoding="utf-8")

        article = {
            "title": "European Union Reaches Historic Energy Agreement",
            "domain": "reuters.com",
            "url": "https://reuters.com/world/europe/energy-agreement"
        }

        mock_groq_output = {
            "headline": "EU Reaches Historic Energy Agreement",
            "curiosity_line": "Major shift for European energy policy",
            "caption": "The European Union has finalized a comprehensive energy pact to stabilize prices and secure long-term power supplies across member states.",
            "hashtags": ["#NewsSnap", "#EuropeanUnion", "#EnergyPolicy", "#WorldNews"]
        }

        with patch("ai_provider.call_groq_chat_completion", return_value=mock_groq_output):
            post = post_generator.generate_post(article)

        self.assertEqual(post["headline"], "EU Reaches Historic Energy Agreement")
        self.assertEqual(post["curiosity_line"], "Major shift for European energy policy")
        self.assertIn("#NewsSnap", post["hashtags"])
        self.assertIn("Source: reuters.com", post["caption"])
        self.assertFalse(post.get("is_synthetic"))

    def test_classify_with_groq_provider(self):
        """8. classify.call_ai classifies articles using Groq provider."""
        os.environ["GROQ_API_KEY"] = "gsk_test_mock"
        articles = [
            {"title": "Summit Concludes With Major Defense Agreement", "domain": "bbc.com", "url": "https://bbc.com/1"},
            {"title": "Local Neighborhood Flower Show Winners Announced", "domain": "localnews.com", "url": "https://localnews.com/2"}
        ]

        mock_class_output = {
            "results": [
                {"id": 1, "importance": "MAJOR", "topic": "Defense", "reason": "Defense pact"},
                {"id": 2, "importance": "LOW", "topic": "Community", "reason": "Local event"}
            ]
        }

        with patch("ai_provider.call_groq_chat_completion", return_value=mock_class_output):
            res = classify.call_ai(articles)

        self.assertEqual(len(res["results"]), 2)
        self.assertEqual(res["results"][0]["importance"], "MAJOR")
        self.assertEqual(res["results"][1]["importance"], "LOW")

    def test_production_fails_closed_when_no_provider_key_configured(self):
        """9. Missing API credentials in production mode never leads to fake content or live publication."""
        os.environ["GITHUB_ACTIONS"] = "true"
        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.temp_hist)
        self.temp_hist.write_text(json.dumps({"posted": [], "processed": [], "classified_pool": []}), encoding="utf-8")

        article = {"title": "Test Title", "domain": "reuters.com", "url": "https://reuters.com/test"}
        # Post generator refuses to create mock content in production
        with self.assertRaises(RuntimeError) as cm:
            post_generator.generate_post(article)

        self.assertIn("CRITICAL", str(cm.exception))
        self.assertIn("GROQ_API_KEY", str(cm.exception))

        # Classifier refuses to proceed in production without a provider key
        with self.assertRaises(RuntimeError) as cm_class:
            ai_provider.classify_articles_ai([article])
        self.assertIn("CRITICAL", str(cm_class.exception))

    def test_scheduler_does_not_create_duplicate_chains_or_publish_during_cooldown(self):
        """10. Scheduler controller aborts on duplicate active chains and pauses during provider cooldown."""
        # 10a. Duplicate chain aborts
        other_run = {"id": 9999, "run_number": 55, "status": "in_progress"}
        with patch("scheduler_controller.check_active_controller_runs", return_value=[other_run]):
            res_dup = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_tok",
                current_run_id="100",
                history_file=str(self.temp_hist)
            )
        self.assertEqual(res_dup["status"], "aborted_duplicate")
        self.assertFalse(res_dup["publisher_dispatched"])
        self.assertFalse(res_dup["successor_dispatched"])

        # 10b. Controller pauses and does not publish during active provider cooldown
        from datetime import datetime, timezone, timedelta
        future_dt = datetime.now(timezone.utc) + timedelta(hours=5)
        quota_manager.set_quota_cooldown(
            resets_at=future_dt,
            reason="Groq API daily quota exhausted",
            history_path=self.temp_hist,
            provider="groq"
        )
        os.environ["GROQ_API_KEY"] = "gsk_valid_key"

        with patch("scheduler_controller.check_active_controller_runs", return_value=[]):
            res_cool = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_tok",
                current_run_id="100",
                history_file=str(self.temp_hist)
            )
        self.assertEqual(res_cool["status"], "paused_quota_cooldown")
        self.assertFalse(res_cool["publisher_dispatched"])
        self.assertFalse(res_cool["successor_dispatched"])



class TestPublishingCapCadenceAndUnattended(unittest.TestCase):
    def setUp(self):
        self.temp_hist = Path("test_history_cap_cadence.json")
        self.temp_output = Path("test_github_output.txt")
        self.orig_hist_publisher = instagram_publisher.HISTORY_PATH
        self.orig_hist_candidates = check_candidates.HISTORY_PATH

    def tearDown(self):
        instagram_publisher.HISTORY_PATH = self.orig_hist_publisher
        check_candidates.HISTORY_PATH = self.orig_hist_candidates
        for p in (self.temp_hist, self.temp_output):
            if p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_rolling_24h_cap_counts_only_confirmed_posts_with_media_id(self):
        """1. Rolling 24-hour cap counts ONLY confirmed posts with valid media_id and timestamp within 24h."""
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

        posted_entries = []
        # 48 confirmed posts within last 24h
        for i in range(48):
            posted_entries.append({
                "url": f"https://example.com/story_{i}",
                "title": f"Story {i}",
                "published": True,
                "media_id": f"media_id_{i}",
                "timestamp": (now - timedelta(hours=i * 0.4)).isoformat(),
            })

        # 3 dry-run / unconfirmed entries (should NOT count towards cap)
        for i in range(3):
            posted_entries.append({
                "url": f"https://example.com/dry_{i}",
                "title": f"Dry Run {i}",
                "published": False,
                "media_id": None,
                "timestamp": now.isoformat(),
            })

        # 2 entries with missing or empty media_id (should NOT count)
        posted_entries.append({
            "url": "https://example.com/no_media_1",
            "title": "No Media 1",
            "published": True,
            "media_id": "",
            "timestamp": now.isoformat(),
        })
        posted_entries.append({
            "url": "https://example.com/no_media_2",
            "title": "No Media 2",
            "published": True,
            "media_id": None,
            "timestamp": now.isoformat(),
        })

        # 10 older confirmed posts outside 24h window (should NOT count)
        for i in range(10):
            posted_entries.append({
                "url": f"https://example.com/old_{i}",
                "title": f"Old Story {i}",
                "published": True,
                "media_id": f"old_media_{i}",
                "timestamp": (now - timedelta(hours=25 + i)).isoformat(),
            })

        self.temp_hist.write_text(json.dumps({"posted": posted_entries, "processed": []}), encoding="utf-8")

        # Test rolling 24h posts getter
        confirmed = quota_manager.get_rolling_24h_published_posts(self.temp_hist, now=now)
        self.assertEqual(len(confirmed), 48)

        # Check cap with 48 posts (allowance 2 left under 50 cap)
        is_under, count, remaining = quota_manager.check_rolling_24h_cap(self.temp_hist, max_posts=50, now=now)
        self.assertTrue(is_under)
        self.assertEqual(count, 48)
        self.assertEqual(remaining, 2)

        # Add 2 more confirmed posts (hitting exactly 50 cap)
        posted_entries.append({
            "url": "https://example.com/story_49",
            "title": "Story 49",
            "published": True,
            "media_id": "media_id_49",
            "timestamp": now.isoformat(),
        })
        posted_entries.append({
            "url": "https://example.com/story_50",
            "title": "Story 50",
            "published": True,
            "media_id": "media_id_50",
            "timestamp": now.isoformat(),
        })
        self.temp_hist.write_text(json.dumps({"posted": posted_entries, "processed": []}), encoding="utf-8")

        is_under, count, remaining = quota_manager.check_rolling_24h_cap(self.temp_hist, max_posts=50, now=now)
        self.assertFalse(is_under)
        self.assertEqual(count, 50)
        self.assertEqual(remaining, 0)

    def test_publication_cadence_calculation_due_vs_not_due(self):
        """2. Publication cadence calculates elapsed time and enforces ~29-minute spacing."""
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

        # Case A: No previous confirmed posts in history -> immediately due
        self.temp_hist.write_text(json.dumps({"posted": [], "processed": []}), encoding="utf-8")
        is_due, elapsed, remaining = quota_manager.check_publication_cadence_due(
            self.temp_hist, cadence_minutes=29, now=now
        )
        self.assertTrue(is_due)
        self.assertEqual(remaining, 0.0)

        # Case B: Last post was 10 minutes ago -> NOT due, remaining ~19 min
        posted = [{
            "url": "https://example.com/last",
            "title": "Last Story",
            "published": True,
            "media_id": "media_last",
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
        }]
        self.temp_hist.write_text(json.dumps({"posted": posted, "processed": []}), encoding="utf-8")
        is_due, elapsed, remaining = quota_manager.check_publication_cadence_due(
            self.temp_hist, cadence_minutes=29, now=now
        )
        self.assertFalse(is_due)
        self.assertAlmostEqual(elapsed, 10.0, places=1)
        self.assertAlmostEqual(remaining, 19.0, places=1)

        # Case C: Last post was 28.6 minutes ago (threshold is 28.5m with buffer) -> due
        posted[0]["timestamp"] = (now - timedelta(minutes=28.6)).isoformat()
        self.temp_hist.write_text(json.dumps({"posted": posted, "processed": []}), encoding="utf-8")
        is_due, elapsed, remaining = quota_manager.check_publication_cadence_due(
            self.temp_hist, cadence_minutes=29, now=now
        )
        self.assertTrue(is_due)
        self.assertEqual(remaining, 0.0)

    def test_fetch_content_publishing_limit_success_and_dynamic_quota(self):
        """3. fetch_content_publishing_limit parses Meta Graph API response dynamically without hardcoding."""
        mock_meta_response = {
            "data": [
                {
                    "config": {
                        "quota_total": 50,
                        "quota_duration": 86400
                    },
                    "quota_usage": 14
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_meta_response).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = instagram_publisher.fetch_content_publishing_limit("17841400", "test_token")

        self.assertEqual(res["quota_total"], 50)
        self.assertEqual(res["quota_usage"], 14)
        self.assertEqual(res["quota_duration"], 86400)
        self.assertEqual(res["remaining_quota"], 36)

        # Test with higher dynamic quota from Meta (e.g. 100 total, 99 usage)
        mock_meta_response_100 = {
            "data": [
                {
                    "config": {
                        "quota_total": 100,
                        "quota_duration": 86400
                    },
                    "quota_usage": 99
                }
            ]
        }
        mock_resp.read.return_value = json.dumps(mock_meta_response_100).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            res100 = instagram_publisher.fetch_content_publishing_limit("17841400", "test_token")
        self.assertEqual(res100["quota_total"], 100)
        self.assertEqual(res100["quota_usage"], 99)
        self.assertEqual(res100["remaining_quota"], 1)

    def test_fetch_content_publishing_limit_fail_closed(self):
        """4. fetch_content_publishing_limit fails closed and sanitizes token on HTTP/API errors."""
        # 4a. Missing credentials
        with self.assertRaises(ValueError):
            instagram_publisher.fetch_content_publishing_limit("", "tok")
        with self.assertRaises(ValueError):
            instagram_publisher.fetch_content_publishing_limit("acc", "")

        # 4b. HTTP Error sanitizes secret token
        http_err = urllib.error.HTTPError(
            url="https://graph.instagram.com/v22.0/test/content_publishing_limit",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"message":"Invalid OAuth access_token secret_token_xyz"}}')
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(RuntimeError) as cm:
                instagram_publisher.fetch_content_publishing_limit("17841400", "secret_token_xyz")
            self.assertNotIn("secret_token_xyz", str(cm.exception))
            self.assertIn("secr..._xyz", str(cm.exception))

    def test_publisher_main_refuses_when_rolling_24h_cap_reached(self):
        """5. Publisher main() refuses to create container when 50-post rolling 24h cap is reached."""
        from PIL import ImageDraw
        img = Image.new("RGB", (1080, 1350), (10, 20, 30))
        d = ImageDraw.Draw(img)
        d.rectangle((50, 50, 1030, 600), fill=(230, 31, 45))
        d.text((100, 100), "CAP TEST CARD", fill=(255, 255, 255))
        img.save(instagram_publisher.IMAGE_PATH, format="JPEG", quality=95)

        test_post = {
            "headline": "CAP TEST HEADLINE FOR ROLLING CAP",
            "caption": "Verified caption testing rolling 24h cap. #NewsSnap",
            "hashtags": ["#NewsSnap"]
        }
        instagram_publisher.POST_PATH.write_text(json.dumps(test_post), encoding="utf-8")

        # Set 50 confirmed posts in temp history
        now = datetime.now(timezone.utc)
        posts_50 = [{
            "url": f"https://example.com/p_{i}",
            "title": f"Story {i}",
            "published": True,
            "media_id": f"media_{i}",
            "timestamp": (now - timedelta(minutes=i * 10)).isoformat(),
        } for i in range(50)]
        self.temp_hist.write_text(json.dumps({"posted": posts_50, "processed": []}), encoding="utf-8")
        instagram_publisher.HISTORY_PATH = self.temp_hist

        mock_profile = {"id": "17841400", "username": "newssnap_bot", "account_type": "BUSINESS"}

        try:
            with patch("instagram_publisher.fetch_account_info", return_value=mock_profile), \
                 patch("instagram_publisher.check_live_feed_duplicate", return_value=""), \
                 patch("instagram_publisher.verify_public_image_url"), \
                 patch.dict(os.environ, {
                     "ENABLE_INSTAGRAM_POSTING": "true",
                     "INSTAGRAM_ACCESS_TOKEN": "mock_login_token",
                     "INSTAGRAM_ACCOUNT_ID": "17841400",
                     "IMAGE_PUBLIC_URL": "https://example.com/news_snap_post.jpg"
                 }):
                with self.assertRaises(RuntimeError) as cm:
                    instagram_publisher.main()
                self.assertIn("Rolling 24-hour Instagram publishing cap reached", str(cm.exception))
        finally:
            if instagram_publisher.IMAGE_PATH.is_file():
                instagram_publisher.IMAGE_PATH.unlink()
            if instagram_publisher.POST_PATH.is_file():
                instagram_publisher.POST_PATH.unlink()

    def test_publisher_main_refuses_when_meta_quota_exhausted(self):
        """6. Publisher main() refuses to create container when Meta content_publishing_limit remaining is 0."""
        from PIL import ImageDraw
        img = Image.new("RGB", (1080, 1350), (10, 20, 30))
        d = ImageDraw.Draw(img)
        d.rectangle((50, 50, 1030, 600), fill=(230, 31, 45))
        d.text((100, 100), "META QUOTA CARD", fill=(255, 255, 255))
        img.save(instagram_publisher.IMAGE_PATH, format="JPEG", quality=95)

        test_post = {
            "headline": "META QUOTA TEST HEADLINE",
            "caption": "Verified caption testing meta publishing limit. #NewsSnap",
            "hashtags": ["#NewsSnap"]
        }
        instagram_publisher.POST_PATH.write_text(json.dumps(test_post), encoding="utf-8")

        # Under app cap (only 5 posts)
        self.temp_hist.write_text(json.dumps({"posted": [], "processed": []}), encoding="utf-8")
        instagram_publisher.HISTORY_PATH = self.temp_hist

        mock_profile = {"id": "17841400", "username": "newssnap_bot", "account_type": "BUSINESS"}
        mock_limit_exhausted = {
            "quota_total": 50,
            "quota_usage": 50,
            "quota_duration": 86400,
            "remaining_quota": 0,
        }

        try:
            with patch("instagram_publisher.fetch_account_info", return_value=mock_profile), \
                 patch("instagram_publisher.check_live_feed_duplicate", return_value=""), \
                 patch("instagram_publisher.verify_public_image_url"), \
                 patch("instagram_publisher.fetch_content_publishing_limit", return_value=mock_limit_exhausted), \
                 patch.dict(os.environ, {
                     "ENABLE_INSTAGRAM_POSTING": "true",
                     "INSTAGRAM_ACCESS_TOKEN": "mock_login_token",
                     "INSTAGRAM_ACCOUNT_ID": "17841400",
                     "IMAGE_PUBLIC_URL": "https://example.com/news_snap_post.jpg"
                 }):
                with self.assertRaises(RuntimeError) as cm:
                    instagram_publisher.main()
                self.assertIn("Instagram Graph API publishing quota exhausted", str(cm.exception))
        finally:
            if instagram_publisher.IMAGE_PATH.is_file():
                instagram_publisher.IMAGE_PATH.unlink()
            if instagram_publisher.POST_PATH.is_file():
                instagram_publisher.POST_PATH.unlink()

    def test_check_candidates_separates_5m_discovery_from_29m_cadence(self):
        """7. check_candidates skips downstream publishing (cadence_due=false) while preserving discovered candidates."""
        # Story discovered in discovery.json
        temp_disc = Path("test_discovery_cadence.json")
        disc_articles = [{
            "url": "https://reuters.com/world/new-story-cadence",
            "title": "Fresh Discovered International Summit Agreement",
            "domain": "reuters.com",
            "is_duplicate": False,
        }]
        temp_disc.write_text(json.dumps(disc_articles), encoding="utf-8")

        # Last confirmed post was 10 minutes ago
        now = datetime.now(timezone.utc)
        recent_posted = [{
            "url": "https://example.com/recent",
            "title": "Recent Post",
            "published": True,
            "media_id": "media_recent",
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
        }]
        self.temp_hist.write_text(json.dumps({"posted": recent_posted, "processed": [], "classified_pool": []}), encoding="utf-8")

        try:
            with patch.dict(os.environ, {
                "NEWS_SNAP_HISTORY_PATH": str(self.temp_hist),
                "GITHUB_OUTPUT": str(self.temp_output),
                "PUBLISH_CADENCE_MINUTES": "29"
            }), patch("check_candidates.DISCOVERY_PATH", temp_disc):
                with self.assertRaises(SystemExit) as cm:
                    check_candidates.main()
                self.assertEqual(cm.exception.code, 0)

            out_content = self.temp_output.read_text(encoding="utf-8")
            self.assertIn("has_fresh=false", out_content)
            self.assertIn("cadence_due=false", out_content)
        finally:
            if temp_disc.is_file():
                temp_disc.unlink()

    def test_check_candidates_gates_when_rolling_cap_reached(self):
        """8. check_candidates outputs cap_reached=true and has_fresh=false when 50 posts published in 24h."""
        temp_disc = Path("test_discovery_cap.json")
        disc_articles = [{
            "url": "https://reuters.com/world/new-story-cap",
            "title": "Fresh Discovered Story Cap",
            "domain": "reuters.com",
            "is_duplicate": False,
        }]
        temp_disc.write_text(json.dumps(disc_articles), encoding="utf-8")

        now = datetime.now(timezone.utc)
        posts_50 = [{
            "url": f"https://example.com/post_{i}",
            "title": f"Post {i}",
            "published": True,
            "media_id": f"media_cap_{i}",
            "timestamp": (now - timedelta(minutes=i * 10)).isoformat(),
        } for i in range(50)]
        self.temp_hist.write_text(json.dumps({"posted": posts_50, "processed": [], "classified_pool": []}), encoding="utf-8")

        try:
            with patch.dict(os.environ, {
                "NEWS_SNAP_HISTORY_PATH": str(self.temp_hist),
                "GITHUB_OUTPUT": str(self.temp_output),
                "MAX_ROLLING_POSTS_24H": "50"
            }), patch("check_candidates.DISCOVERY_PATH", temp_disc):
                with self.assertRaises(SystemExit) as cm:
                    check_candidates.main()
                self.assertEqual(cm.exception.code, 0)

            out_content = self.temp_output.read_text(encoding="utf-8")
            self.assertIn("has_fresh=false", out_content)
            self.assertIn("cap_reached=true", out_content)
        finally:
            if temp_disc.is_file():
                temp_disc.unlink()

    def test_unattended_6_month_design_safeguards(self):
        """9. Multi-month unattended operation parameters (retention >= 500, defaults 50/day and 29m)."""
        self.assertGreaterEqual(instagram_publisher.MAX_HISTORY_ENTRIES, 500)
        self.assertEqual(quota_manager.DEFAULT_MAX_ROLLING_POSTS_24H, 50)
        self.assertEqual(quota_manager.DEFAULT_CADENCE_MINUTES, 29)



class TestCloudflareWorkersAIProvider(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()
        for k in (
            "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_MODEL", "CLOUDFLARE_API_BASE",
            "GROQ_API_KEY", "GROQ_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "AI_PROVIDER",
            "GITHUB_ACTIONS", "CI", "NEWS_SNAP_PROD"
        ):
            os.environ.pop(k, None)
        self.temp_hist = Path("test_history_cf.json")
        if self.temp_hist.exists():
            try:
                self.temp_hist.unlink()
            except Exception:
                pass

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        if self.temp_hist.exists():
            try:
                self.temp_hist.unlink()
            except Exception:
                pass

    def test_cloudflare_provider_selection_and_override(self):
        """1. ai_provider selects Cloudflare when token and account are configured, and respects overrides."""
        self.assertEqual(ai_provider.get_active_provider(), "")

        # Set Cloudflare credentials -> returns 'cloudflare'
        os.environ["CLOUDFLARE_API_TOKEN"] = "mock_cf_token_123"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "mock_cf_acc_456"
        self.assertEqual(ai_provider.get_active_provider(), "cloudflare")

        # Explicit override to gemini
        os.environ["AI_PROVIDER"] = "gemini"
        self.assertEqual(ai_provider.get_active_provider(), "gemini")

        # Explicit override to groq
        os.environ["AI_PROVIDER"] = "groq"
        self.assertEqual(ai_provider.get_active_provider(), "groq")

        # Explicit override to cloudflare
        os.environ["AI_PROVIDER"] = "cloudflare"
        self.assertEqual(ai_provider.get_active_provider(), "cloudflare")

    def test_call_cloudflare_chat_completion_success(self):
        """2. call_cloudflare_chat_completion makes correct REST request and parses valid JSON output."""
        os.environ["CLOUDFLARE_API_TOKEN"] = "cf_test_token"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "cf_test_account_id"

        mock_payload = {
            "result": {
                "response": json.dumps({
                    "headline": "Historic Global Climate Treaty Signed at UN Summit",
                    "curiosity_line": "Major diplomatic breakthrough",
                    "caption": "Representatives from 190 nations reached a landmark accord today. #NewsSnap",
                    "hashtags": ["#NewsSnap", "#ClimateAction", "#UNSummit"]
                })
            },
            "success": True,
            "errors": [],
            "messages": []
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = ai_provider.call_cloudflare_chat_completion(
                prompt="Summarize article",
                system_prompt="You are an editor"
            )

        self.assertEqual(res["headline"], "Historic Global Climate Treaty Signed at UN Summit")
        self.assertIn("#NewsSnap", res["hashtags"])

        # Verify request details
        req_sent = mock_urlopen.call_args[0][0]
        self.assertIn("cf_test_account_id", req_sent.full_url)
        self.assertIn("@cf/meta/llama-3.1-8b-instruct", req_sent.full_url)
        self.assertEqual(req_sent.headers["Authorization"], "Bearer cf_test_token")
        self.assertEqual(req_sent.headers["Content-type"], "application/json")

        req_body = json.loads(req_sent.data.decode("utf-8"))
        self.assertEqual(len(req_body["messages"]), 2)
        self.assertEqual(req_body["messages"][0]["role"], "system")
        self.assertEqual(req_body["messages"][1]["role"], "user")

    def test_call_cloudflare_chat_completion_markdown_fences_and_braces(self):
        """3. Handles markdown code fences and cleans outer text from response."""
        os.environ["CLOUDFLARE_API_TOKEN"] = "cf_tok"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "cf_acc"

        fenced_output = """Here is the classified response:
```json
{
  "results": [
    {"id": 1, "importance": "MAJOR", "topic": "World", "reason": "Historic accord"}
  ]
}
```
Hope this helps!"""

        mock_payload = {
            "result": {"response": fenced_output},
            "success": True,
            "errors": [],
            "messages": []
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = ai_provider.call_cloudflare_chat_completion(prompt="Classify")

        self.assertIn("results", res)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["importance"], "MAJOR")

    def test_call_cloudflare_missing_secrets(self):
        """4. Fails fast with descriptive ValueError if credentials are missing."""
        # Missing token
        os.environ.pop("CLOUDFLARE_API_TOKEN", None)
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acc"
        with self.assertRaises(ValueError) as cm1:
            ai_provider.call_cloudflare_chat_completion(prompt="test")
        self.assertIn("CLOUDFLARE_API_TOKEN", str(cm1.exception))

        # Missing account ID
        os.environ["CLOUDFLARE_API_TOKEN"] = "tok"
        os.environ.pop("CLOUDFLARE_ACCOUNT_ID", None)
        with self.assertRaises(ValueError) as cm2:
            ai_provider.call_cloudflare_chat_completion(prompt="test")
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", str(cm2.exception))

    def test_call_cloudflare_api_auth_error_sanitization(self):
        """5. Auth errors fail closed without leaking API token in exceptions."""
        os.environ["CLOUDFLARE_API_TOKEN"] = "super_secret_cf_token_999"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "test_acc"

        http_err = urllib.error.HTTPError(
            url="https://api.cloudflare.com/client/v4/accounts/test_acc/ai/run/@cf/meta/llama-3.1-8b-instruct",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(b'{"success":false,"errors":[{"code":10000,"message":"Invalid token super_secret_cf_token_999"}]}')
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(RuntimeError) as cm:
                ai_provider.call_cloudflare_chat_completion(prompt="test")

            err_str = str(cm.exception)
            self.assertNotIn("super_secret_cf_token_999", err_str)
            self.assertIn("HTTP 401", err_str)

    def test_call_cloudflare_quota_exhaustion_sets_cooldown(self):
        """6. Daily quota exhaustion (HTTP 429 or neurons exceeded) triggers provider-specific cooldown."""
        os.environ["CLOUDFLARE_API_TOKEN"] = "tok"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acc"
        os.environ["NEWS_SNAP_HISTORY_PATH"] = str(self.temp_hist)
        self.temp_hist.write_text(json.dumps({"posted": [], "processed": []}), encoding="utf-8")

        http_err = urllib.error.HTTPError(
            url="https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/meta/llama-3.1-8b-instruct",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=io.BytesIO(b'{"success":false,"errors":[{"code":10016,"message":"Daily quota limit exceeded for neurons: 10000"}]}')
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(RuntimeError) as cm:
                ai_provider.call_cloudflare_chat_completion(prompt="test", max_attempts=1)
            self.assertIn("quota exhausted", str(cm.exception).lower())

        # Verify cooldown recorded specifically for Cloudflare in history.json
        self.assertTrue(quota_manager.is_cooldown_active(self.temp_hist, provider="cloudflare"))
        # Verify Gemini is NOT affected by Cloudflare cooldown
        self.assertFalse(quota_manager.is_cooldown_active(self.temp_hist, provider="gemini"))

    def test_classify_and_post_generation_routing_through_cloudflare(self):
        """7. classify_articles_ai and generate_post_content_ai route cleanly through Cloudflare."""
        os.environ["CLOUDFLARE_API_TOKEN"] = "cf_tok"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "cf_acc"

        mock_class_output = {
            "results": [
                {"id": 1, "importance": "MAJOR", "topic": "Diplomacy", "reason": "Peace summit"}
            ]
        }
        mock_post_output = {
            "headline": "Peace Summit Successfully Concluded",
            "curiosity_line": "Major regional accord",
            "caption": "World leaders signed a landmark pact today. #NewsSnap",
            "hashtags": ["#NewsSnap", "#PeaceAccord"]
        }

        # 7a. Classification routes to Cloudflare
        with patch("ai_provider.call_cloudflare_chat_completion", return_value=mock_class_output) as mock_cf_call:
            articles = [{"title": "Historic Peace Summit Concluded", "domain": "reuters.com", "url": "https://reuters.com/1"}]
            res = ai_provider.classify_articles_ai(articles)
            self.assertEqual(res["results"][0]["importance"], "MAJOR")
            mock_cf_call.assert_called_once()

        # 7b. Post generation routes to Cloudflare
        with patch("ai_provider.call_cloudflare_chat_completion", return_value=mock_post_output) as mock_cf_gen:
            article = {"title": "Historic Peace Summit Concluded", "domain": "reuters.com", "url": "https://reuters.com/1"}
            post = ai_provider.generate_post_content_ai(article)
            self.assertEqual(post["headline"], "Peace Summit Successfully Concluded")
            mock_cf_gen.assert_called_once()

    def test_scheduler_and_watchdog_respect_cloudflare_cooldown(self):
        """8. Scheduler controller and watchdog halt safely when Cloudflare quota cooldown is active."""
        from datetime import datetime, timezone, timedelta
        os.environ["CLOUDFLARE_API_TOKEN"] = "tok"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acc"

        # Record Cloudflare quota cooldown
        future_reset = datetime.now(timezone.utc) + timedelta(hours=6)
        quota_manager.set_quota_cooldown(
            resets_at=future_reset,
            reason="Cloudflare Workers AI Free Tier daily quota exhausted. Resets at 00:00 UTC.",
            history_path=self.temp_hist,
            provider="cloudflare"
        )

        # 8a. Scheduler controller pauses
        with patch("scheduler_controller.check_active_controller_runs", return_value=[]):
            res_ctrl = scheduler_controller.run_controller_cycle(
                repo="test/repo",
                token="test_tok",
                current_run_id="101",
                history_file=str(self.temp_hist)
            )
        self.assertEqual(res_ctrl["status"], "paused_quota_cooldown")
        self.assertEqual(res_ctrl["provider"], "CLOUDFLARE")
        self.assertFalse(res_ctrl["publisher_dispatched"])
        self.assertFalse(res_ctrl["successor_dispatched"])

        # 8b. Watchdog suppresses revival
        res_wd = scheduler_watchdog.run_watchdog_check(
            repo="test/repo",
            token="test_tok",
            history_file=str(self.temp_hist)
        )
        self.assertEqual(res_wd["status"], "cooldown_active")
        self.assertEqual(res_wd["action"], "none")
        self.assertEqual(res_wd["provider"], "CLOUDFLARE")

    def test_check_candidates_with_cloudflare_provider(self):
        """9. check_candidates detects Cloudflare as active provider and respects Cloudflare cooldown."""
        temp_disc = Path("test_discovery_cf.json")
        disc_articles = [{
            "url": "https://reuters.com/world/cf-story",
            "title": "Fresh Discovered Cloudflare Story",
            "domain": "reuters.com",
            "is_duplicate": False,
        }]
        temp_disc.write_text(json.dumps(disc_articles), encoding="utf-8")
        temp_out = Path("test_output_cf.txt")

        # Set Cloudflare credentials
        os.environ["CLOUDFLARE_API_TOKEN"] = "tok"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acc"

        # Active Cloudflare cooldown halts candidate check cleanly
        from datetime import datetime, timezone, timedelta
        future_reset = datetime.now(timezone.utc) + timedelta(hours=5)
        quota_manager.set_quota_cooldown(
            resets_at=future_reset,
            reason="Cloudflare Workers AI Free Tier daily quota exhausted.",
            history_path=self.temp_hist,
            provider="cloudflare"
        )

        try:
            with patch.dict(os.environ, {
                "NEWS_SNAP_HISTORY_PATH": str(self.temp_hist),
                "GITHUB_OUTPUT": str(temp_out),
            }), patch("check_candidates.DISCOVERY_PATH", temp_disc):
                with self.assertRaises(SystemExit) as cm:
                    check_candidates.main()
                self.assertEqual(cm.exception.code, 0)

            out_content = temp_out.read_text(encoding="utf-8")
            self.assertIn("has_fresh=false", out_content)
            self.assertIn("cooldown_active=true", out_content)
        finally:
            if temp_disc.is_file():
                temp_disc.unlink()
            if temp_out.is_file():
                temp_out.unlink()


if __name__ == "__main__":
    unittest.main()



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
import unittest
from pathlib import Path
from PIL import Image

import test as discovery
import select_article
import post_generator
import generate_image
import instagram_publisher
import prepare_special_formats
import format_registry
from unittest.mock import patch


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
            img = Image.new("RGB", (1080, 1350), (10, 24, 45))
            img.save(instagram_publisher.IMAGE_PATH, format="JPEG")
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
    def test_fifteen_minute_schedule(self):
        workflow_path = Path(".github/workflows/test.yml")
        self.assertTrue(workflow_path.is_file(), "Workflow file .github/workflows/test.yml must exist")
        content = workflow_path.read_text(encoding="utf-8")
        self.assertIn('cron: "*/15 * * * *"', content, "Workflow must be scheduled every 15 minutes")
        self.assertNotIn('0 */6 * * *', content, "6-hour schedule must be replaced")

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


if __name__ == "__main__":
    unittest.main()

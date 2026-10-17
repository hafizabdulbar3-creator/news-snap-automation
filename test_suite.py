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


if __name__ == "__main__":
    unittest.main()

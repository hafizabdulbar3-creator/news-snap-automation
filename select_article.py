import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from source_allowlist import (
    is_approved_url,
    get_canonical_domain,
    check_topic_diversity,
    extract_topic_entities,
    KNOWN_ENTITIES,
    APPROVED_DOMAINS,
)

DEFAULT_RETENTION_HOURS = int(os.environ.get("DRY_RUN_RETENTION_HOURS", "48"))


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_genuine_article(title: str, url: str) -> bool:
    t_low = title.lower()
    if any(pat in t_low for pat in ("latest news & updates", "latest news and updates", "news archives", "category archives")):
        return False
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith(("/technology", "/world", "/business", "/politics", "/opinion", "/entertainment", "/energy-and-climate")):
        return False
    return True


def is_candidate_eligible(
    article: dict,
    classification: dict,
    recently_posted: set,
    recently_processed: set,
    posted_history: list
) -> tuple[bool, str]:
    """Strictly verify URL validity, approved whitelist domain, non-duplicate status, and topic diversity."""
    url = str(article.get("url", "")).strip()
    title = str(article.get("title", "")).strip()

    if not is_valid_url(url) or len(title.split()) < 4 or not is_genuine_article(title, url):
        return False, "invalid url structure or non-genuine article"

    # Absolute Domain Whitelist Enforcement
    if not is_approved_url(url):
        return False, f"url domain '{article.get('domain')}' not on approved news whitelist"

    url_low = url.lower()
    title_low = title.lower()
    if (url_low in recently_posted or title_low in recently_posted or
        url_low in recently_processed or title_low in recently_processed):
        return False, "duplicate (already posted or processed)"

    # Rolling Topic Diversity Safeguard: Max 2 posts per entity/topic in last 10 posts
    allowed, div_reason = check_topic_diversity(title, posted_history, max_same_topic=2, window_size=10)
    if not allowed:
        return False, div_reason

    return True, "eligible"


def emit_article_selected(selected: bool) -> None:
    """Emit article_selected output for GitHub Actions workflow gating."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        try:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"article_selected={'true' if selected else 'false'}\n")
        except Exception as e:
            print(f"[WARN] Failed to write to GITHUB_OUTPUT: {e}")


def rank_by_diversity_preference(candidates: list[dict], posted_history: list[dict]) -> dict | None:
    """When multiple eligible stories exist, prefer diversity across publishers, people, and topics.

    If only one eligible story exists, returns it directly without forcing artificial variety.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Extract recent confirmed published posts (up to last 5 posts)
    recent_published = [p for p in posted_history if p.get("published") is not False][-5:]
    recent_domains = [str(p.get("domain", "")).lower() for p in recent_published]
    last_domain = recent_domains[-1] if recent_domains else ""

    # Count recent entity appearances across recent posts
    recent_entity_counts = {}
    for p in recent_published:
        p_title = p.get("headline") or p.get("title") or ""
        p_entities = extract_topic_entities(p_title)
        for e in p_entities:
            if e in KNOWN_ENTITIES:
                recent_entity_counts[e] = recent_entity_counts.get(e, 0) + 1

    scored = []
    for cand in candidates:
        base_score = float(cand.get("score", 0))
        title = cand.get("title", "")
        domain = str(cand.get("domain", "")).lower()
        cand_entities = extract_topic_entities(title)

        diversity_penalty = 0.0

        # 1. Person/Entity recency penalty:
        # If the candidate focuses on an entity (e.g. Trump, Biden) already published recently,
        # apply a penalty so alternative diverse stories are preferred when alternatives exist.
        for e in cand_entities:
            if e in recent_entity_counts:
                # Heavy penalty if entity appeared in the very last published post
                if recent_published and e in extract_topic_entities(recent_published[-1].get("headline") or recent_published[-1].get("title") or ""):
                    diversity_penalty += 70.0
                else:
                    diversity_penalty += 40.0 * recent_entity_counts[e]

        # 2. Publisher recency penalty:
        # Avoid posting back-to-back from the exact same news organization
        if last_domain and (domain == last_domain or domain.endswith("." + last_domain) or last_domain.endswith("." + domain)):
            diversity_penalty += 35.0

        # 3. Publisher diversity bonus:
        # Reward publishers not seen in the last 3 published posts
        if domain not in recent_domains[-3:]:
            diversity_penalty -= 20.0

        adjusted_score = base_score - diversity_penalty
        scored.append((adjusted_score, cand))

    # Sort descending by adjusted diversity score
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def select_best_article():
    discovery_path = Path("discovery.json")
    classified_path = Path("classified_sample.json")
    history_path = Path("history.json")

    if not discovery_path.is_file():
        raise FileNotFoundError("discovery.json is missing.")
    if not classified_path.is_file():
        raise FileNotFoundError("classified_sample.json is missing.")

    articles = json.loads(discovery_path.read_text(encoding="utf-8"))
    classified_data = json.loads(classified_path.read_text(encoding="utf-8"))

    # Early hygiene: Prune unapproved / licensing-restricted stories from persistent classified_pool
    if history_path.is_file():
        try:
            raw_hist = json.loads(history_path.read_text(encoding="utf-8"))
            if "classified_pool" in raw_hist and isinstance(raw_hist["classified_pool"], list):
                orig_pool_len = len(raw_hist["classified_pool"])
                raw_hist["classified_pool"] = [
                    a for a in raw_hist["classified_pool"]
                    if isinstance(a, dict) and is_approved_url(a.get("url", ""))
                ]
                if len(raw_hist["classified_pool"]) != orig_pool_len:
                    history_path.write_text(json.dumps(raw_hist, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Load history (both published and recently dry-run-processed)
    recently_posted = set()
    recently_processed = set()
    posted_history = []
    if history_path.is_file():
        try:
            hist = json.loads(history_path.read_text(encoding="utf-8"))
            posted_history = hist.get("posted", [])
            for item in posted_history:
                if item.get("published") is True:
                    if item.get("url"):
                        recently_posted.add(item["url"].strip().lower())
                    if item.get("title"):
                        recently_posted.add(item["title"].strip().lower())

            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=DEFAULT_RETENTION_HOURS)
            for item in hist.get("processed", []):
                ts_str = item.get("timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue  # Expired
                    except Exception:
                        pass
                if item.get("url"):
                    recently_processed.add(item["url"].strip().lower())
                if item.get("title"):
                    recently_processed.add(item["title"].strip().lower())
        except Exception:
            pass

    classifications = {
        item["id"]: item
        for item in classified_data.get("results", [])
        if isinstance(item, dict) and "id" in item
    }

    selected = None

    # Pass 1: Look for MAJOR importance, approved whitelist domain, non-duplicate, diverse topic
    major_candidates = []
    for index, article in enumerate(articles[:50], start=1):
        classification = classifications.get(index, {})
        eligible, reason = is_candidate_eligible(
            article, classification, recently_posted, recently_processed, posted_history
        )
        if not eligible:
            continue

        if classification.get("importance") == "MAJOR":
            topic = str(classification.get("topic", "")).lower()
            if "non-english" in topic or "foreign" in topic:
                continue
            major_candidates.append({**article, "classification": classification})

    if major_candidates:
        selected = rank_by_diversity_preference(major_candidates, posted_history)

    # Pass 2: If no MAJOR story found, look for NORMAL importance
    if selected is None:
        normal_candidates = []
        for index, article in enumerate(articles[:50], start=1):
            classification = classifications.get(index, {})
            eligible, reason = is_candidate_eligible(
                article, classification, recently_posted, recently_processed, posted_history
            )
            if not eligible:
                continue

            if classification.get("importance") == "NORMAL":
                topic = str(classification.get("topic", "")).lower()
                if "non-english" in topic or "foreign" in topic:
                    continue
                normal_candidates.append({**article, "classification": classification})

        if normal_candidates:
            selected = rank_by_diversity_preference(normal_candidates, posted_history)

    # Pass 3: Fallback to any valid approved non-duplicate diverse article
    if selected is None:
        fallback_candidates = []
        for index, article in enumerate(articles[:50], start=1):
            classification = classifications.get(index, {})
            eligible, reason = is_candidate_eligible(
                article, classification, recently_posted, recently_processed, posted_history
            )
            if not eligible:
                continue

            fallback_candidates.append({**article, "classification": classification})

        if fallback_candidates:
            selected = rank_by_diversity_preference(fallback_candidates, posted_history)

    if selected is None:
        print("[SAFE SKIP] No publication-authorized, non-duplicate article available for selection.")
        sel_path = Path("selected_article.json")
        if sel_path.is_file():
            try:
                sel_path.unlink()
            except OSError:
                pass
        emit_article_selected(False)
        return None

    # Clean up any stale roundup artifacts from prior runs/tests to prevent silent divergence
    for stale in (Path("roundup.json"), Path("roundup_post.json")):
        if stale.is_file():
            try:
                stale.unlink()
            except Exception:
                pass

    # Normalize canonical domain to verified approved source
    canonical_d = get_canonical_domain(selected.get("url", ""))
    if canonical_d:
        selected["domain"] = canonical_d

    Path("selected_article.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    emit_article_selected(True)

    # Prune unapproved stories from persistent classified_pool
    if history_path.is_file():
        try:
            raw_hist = json.loads(history_path.read_text(encoding="utf-8"))
            if "classified_pool" in raw_hist and isinstance(raw_hist["classified_pool"], list):
                orig_pool_len = len(raw_hist["classified_pool"])
                raw_hist["classified_pool"] = [
                    a for a in raw_hist["classified_pool"]
                    if isinstance(a, dict) and is_approved_url(a.get("url", ""))
                ]
                if len(raw_hist["classified_pool"]) != orig_pool_len:
                    history_path.write_text(json.dumps(raw_hist, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Preserve candidate in classified_pool until confirmed published or processed in instagram_publisher.py
    # This prevents dropping pool candidates if generation, rendering, or publishing fails downstream.

    print("SELECTED ARTICLE:")
    print(f"Title: {selected.get('title')}")
    print(f"Domain: {selected.get('domain')}")
    print(f"URL: {selected.get('url')}")
    print(f"Classification: {selected.get('classification')}")
    return selected


if __name__ == "__main__":
    select_best_article()

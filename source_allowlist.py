"""NEWS SNAP - Strict News Source Whitelist, Publication Licensing & Topic Diversity Engine.

Defines the 22 user-requested news organizations and their 28 verified official domains.
Strictly separates the user's requested source whitelist from the publishers currently
authorized for automated publication.

Enforces licensing restrictions:
- BBC (bbc.com, bbc.co.uk), NDTV (ndtv.com), The Indian Express (indianexpress.com),
  The Hindu (thehindu.com), and LiveMint (livemint.com) remain strictly ineligible
  for automated publication while their required commercial syndication/licence is absent,
  regardless of whether their URLs are discovered via GDELT, RSS, or search.
- Only the other 20 explicitly approved organizations (25 domains) are authorized
  for automated post generation and live Instagram publication.
- Unapproved wire services and aggregators (AP, Reuters, Google News, Flipboard) remain blocked.
- Enforces rolling topic diversity limits (maximum 2 posts per principal person/topic
  within the most recent 10 published posts).
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

SOURCES_FILE = Path(os.environ.get("NEWS_SNAP_SOURCES_PATH", "sources.json"))

# ---------------------------------------------------------------------------
# Blocked Aggregator and Search Index Domains (never valid article publishers)
# ---------------------------------------------------------------------------
BLOCKED_AGGREGATOR_DOMAINS = {
    "gdeltproject.org",
    "data.gdeltproject.org",
    "google.com",
    "news.google.com",
    "flipboard.com",
    "yahoo.com",
    "news.yahoo.com",
}

# ---------------------------------------------------------------------------
# Strict User-Requested Source Discovery Whitelist (22 Organizations)
# GDELT and open-data feeds may only discover canonical URLs from these 22 orgs.
# ---------------------------------------------------------------------------
USER_DISCOVERY_WHITELIST = [
    # International News Organizations (1-12)
    {
        "id": 1,
        "name": "BBC News",
        "category": "international",
        "domains": ["bbc.com", "bbc.co.uk"],
        "feed_status": "unavailable_licensing",
        "publication_authorized": False,
        "feed_reason": "BBC terms restrict RSS use to personal non-commercial display; syndication license required."
    },
    {
        "id": 2,
        "name": "CNN",
        "category": "international",
        "domains": ["cnn.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 3,
        "name": "Fox News",
        "category": "international",
        "domains": ["foxnews.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 4,
        "name": "Al Jazeera",
        "category": "international",
        "domains": ["aljazeera.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 5,
        "name": "Sky News",
        "category": "international",
        "domains": ["news.sky.com", "sky.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 6,
        "name": "Sky News Australia",
        "category": "international",
        "domains": ["skynews.com.au"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 7,
        "name": "Sky News Arabia",
        "category": "international",
        "domains": ["skynewsarabia.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 8,
        "name": "MSNBC",
        "category": "international",
        "domains": ["msnbc.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 9,
        "name": "Bloomberg Television",
        "category": "international",
        "domains": ["bloomberg.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 10,
        "name": "Al Arabiya",
        "category": "international",
        "domains": ["alarabiya.net"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 11,
        "name": "Euronews",
        "category": "international",
        "domains": ["euronews.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 12,
        "name": "NDTV",
        "category": "international_indian",
        "domains": ["ndtv.com"],
        "feed_status": "unavailable_licensing",
        "publication_authorized": False,
        "feed_reason": "NDTV terms prohibit automated social feeds or third-party automated processing without prior written agreement."
    },
    # Indian News Organizations (13-22)
    {
        "id": 13,
        "name": "Aaj Tak",
        "category": "indian",
        "domains": ["aajtak.in"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 14,
        "name": "News18 India",
        "category": "indian",
        "domains": ["news18.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 15,
        "name": "TV9 Bharatvarsh",
        "category": "indian",
        "domains": ["tv9hindi.com", "tv9.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Verified official domains: tv9hindi.com (Hindi news portal), tv9.com (network portal)."
    },
    {
        "id": 16,
        "name": "India TV",
        "category": "indian",
        "domains": ["indiatvnews.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Discovered via canonical URLs in open-data discovery index."
    },
    {
        "id": 17,
        "name": "Republic Bharat",
        "category": "indian",
        "domains": ["republicbharat.com", "republicworld.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Verified official domains: republicbharat.com, republicworld.com."
    },
    {
        "id": 18,
        "name": "Zee News",
        "category": "indian",
        "domains": ["zeenews.com", "zeenews.india.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Verified official domains: zeenews.com, zeenews.india.com (Zee Media properties)."
    },
    {
        "id": 19,
        "name": "ABP News",
        "category": "indian",
        "domains": ["abplive.com", "abpnews.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Verified official domains: abplive.com (digital news portal), abpnews.com."
    },
    {
        "id": 20,
        "name": "Times Now",
        "category": "indian",
        "domains": ["timesnownews.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Verified official domain: timesnownews.com."
    },
    {
        "id": 21,
        "name": "CNN-News18",
        "category": "indian",
        "domains": ["cnnnews18.com", "news18.com"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Verified official properties: news18.com, cnnnews18.com."
    },
    {
        "id": 22,
        "name": "DD News",
        "category": "indian",
        "domains": ["ddnews.gov.in"],
        "feed_status": "discovery_via_gdelt",
        "publication_authorized": True,
        "feed_reason": "Verified official government news domain: ddnews.gov.in."
    }
]

# ---------------------------------------------------------------------------
# Strict Licensing-Restricted Domains
# BBC, NDTV, The Indian Express, The Hindu, and LiveMint
# ---------------------------------------------------------------------------
LICENSING_RESTRICTED_DOMAINS = {
    "bbc.com",
    "bbc.co.uk",
    "ndtv.com",
    "indianexpress.com",
    "thehindu.com",
    "livemint.com",
}

# ---------------------------------------------------------------------------
# Strict Discovery Whitelist Domains (22 organizations across 28 domains)
# ---------------------------------------------------------------------------
DISCOVERY_WHITELIST_DOMAINS = {
    domain.lower()
    for source in USER_DISCOVERY_WHITELIST
    for domain in source["domains"]
}
USER_WHITELISTED_DOMAINS = DISCOVERY_WHITELIST_DOMAINS
ALL_WHITELISTED_DOMAINS = DISCOVERY_WHITELIST_DOMAINS

# ---------------------------------------------------------------------------
# Strict Publication-Authorized Sources and Domains (20 orgs / 25 domains)
# Formed strictly by excluding every source with feed_status == 'unavailable_licensing'
# and excluding every domain in LICENSING_RESTRICTED_DOMAINS.
# ---------------------------------------------------------------------------
APPROVED_NEWS_SOURCES = [
    source for source in USER_DISCOVERY_WHITELIST
    if source.get("feed_status") != "unavailable_licensing"
    and source.get("publication_authorized") is True
]

PUBLICATION_AUTHORIZED_DOMAINS = {
    domain.lower()
    for source in APPROVED_NEWS_SOURCES
    for domain in source["domains"]
    if domain.lower() not in LICENSING_RESTRICTED_DOMAINS
}

APPROVED_DOMAINS = PUBLICATION_AUTHORIZED_DOMAINS


def get_discovery_whitelisted_domains() -> set[str]:
    """Return the set of all 28 domains on the user's requested news discovery whitelist."""
    return set(DISCOVERY_WHITELIST_DOMAINS)


def get_whitelisted_domains() -> set[str]:
    """Alias for discovery whitelisted domains."""
    return set(DISCOVERY_WHITELIST_DOMAINS)


def get_licensing_restricted_domains() -> set[str]:
    """Return the set of domains restricted from automated publication due to licensing."""
    return set(LICENSING_RESTRICTED_DOMAINS)


def get_authorized_domains() -> set[str]:
    """Return the set of 25 domains authorized and eligible for automated publication."""
    return set(PUBLICATION_AUTHORIZED_DOMAINS)


def get_approved_domains() -> set[str]:
    """Return the set of approved official domains eligible for publication."""
    return set(APPROVED_DOMAINS)


def get_discovery_sources() -> list[dict]:
    """Return the list of all 22 user-whitelisted discovery news organizations."""
    return list(USER_DISCOVERY_WHITELIST)


def get_whitelisted_sources() -> list[dict]:
    """Alias for discovery sources."""
    return list(USER_DISCOVERY_WHITELIST)


def get_authorized_sources() -> list[dict]:
    """Return only the 20 news organizations currently authorized for automated publication."""
    return list(APPROVED_NEWS_SOURCES)


def get_approved_sources() -> list[dict]:
    """Return the list of approved news organizations eligible for publication."""
    return list(APPROVED_NEWS_SOURCES)


def is_licensing_restricted(url_or_domain: str) -> bool:
    """Strictly identify if a URL or domain belongs to a licensing-restricted publisher.

    Restricted publishers include:
    - BBC (bbc.com, bbc.co.uk)
    - NDTV (ndtv.com)
    - The Indian Express (indianexpress.com)
    - The Hindu (thehindu.com)
    - LiveMint (livemint.com)
    """
    if not url_or_domain or not isinstance(url_or_domain, str):
        return False
    target = url_or_domain.strip().lower()
    if "://" in target:
        try:
            parsed = urlparse(target)
            target = parsed.hostname or ""
        except Exception:
            pass
    target = target.rstrip(".")
    if ":" in target:
        target = target.split(":", 1)[0]
    if target.startswith("www."):
        target = target[4:]
    if not target:
        return False
    for restricted in LICENSING_RESTRICTED_DOMAINS:
        if target == restricted or target.endswith("." + restricted):
            return True
    return False


def is_discovery_whitelisted_domain(hostname: str) -> bool:
    """Verify if a parsed hostname belongs to any of the user's 22 requested discovery sources.

    Strictly rejects outside publishers (e.g. wnmufm.org, nytimes.com, theguardian.com),
    wire services (apnews.com, reuters.com), and aggregator/index domains (gdeltproject.org).
    """
    if not hostname or not isinstance(hostname, str):
        return False

    clean_host = hostname.strip().lower().rstrip(".")
    if ":" in clean_host:
        clean_host = clean_host.split(":", 1)[0]
    if clean_host.startswith("www."):
        clean_host = clean_host[4:]

    if not clean_host:
        return False

    # Blocked aggregator / search index domains are never article publishers
    if clean_host in BLOCKED_AGGREGATOR_DOMAINS or any(clean_host.endswith("." + b) for b in BLOCKED_AGGREGATOR_DOMAINS):
        return False

    for whitelisted in DISCOVERY_WHITELIST_DOMAINS:
        if clean_host == whitelisted or clean_host.endswith("." + whitelisted):
            return True

    return False


def is_discovery_whitelisted_url(url: str) -> bool:
    """Validate that an article URL belongs to the user's 22-source discovery whitelist."""
    if not url or not isinstance(url, str):
        return False

    clean_url = url.strip()
    try:
        parsed = urlparse(clean_url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        return is_discovery_whitelisted_domain(hostname)
    except Exception:
        return False


is_whitelisted_domain = is_discovery_whitelisted_domain
is_whitelisted_url = is_discovery_whitelisted_url


def is_publication_authorized_domain(hostname: str) -> bool:
    """Strictly verify if a parsed hostname belongs to a publication-authorized news domain.

    Rejects:
    1. Licensing-restricted publishers (BBC, NDTV, The Indian Express, The Hindu, LiveMint).
    2. Any publisher marked 'unavailable_licensing' in the discovery whitelist.
    3. Outside publishers (e.g. wnmufm.org, nytimes.com, washingtonpost.com).
    4. Unapproved wire services / aggregators / indices (AP, Reuters, Google News, Flipboard, GDELT).
    5. Lookalike, attacker, or spoofed domains.
    """
    if not hostname or not isinstance(hostname, str):
        return False

    clean_host = hostname.strip().lower().rstrip(".")
    if ":" in clean_host:
        clean_host = clean_host.split(":", 1)[0]
    if clean_host.startswith("www."):
        clean_host = clean_host[4:]

    if not clean_host:
        return False

    # Fail closed on licensing restricted domains
    if is_licensing_restricted(clean_host):
        return False

    # Blocked aggregator / search index domains are never article publishers
    if clean_host in BLOCKED_AGGREGATOR_DOMAINS or any(clean_host.endswith("." + b) for b in BLOCKED_AGGREGATOR_DOMAINS):
        return False

    # Check authorized domains
    for authorized in PUBLICATION_AUTHORIZED_DOMAINS:
        if clean_host == authorized or clean_host.endswith("." + authorized):
            return True

    return False


def is_publication_authorized_url(url: str) -> bool:
    """Validate that the canonical article URL has a valid scheme and is authorized for publication.

    Aggregators, unapproved sources, outside publishers (e.g. wnmufm.org), and licensing-restricted
    sources (BBC, NDTV, LiveMint, etc.) are rejected.
    """
    if not url or not isinstance(url, str):
        return False

    clean_url = url.strip()
    try:
        parsed = urlparse(clean_url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        return is_publication_authorized_domain(hostname)
    except Exception:
        return False


# Aliases for seamless backward compatibility across pipeline callers
is_approved_domain = is_publication_authorized_domain
is_approved_url = is_publication_authorized_url


def get_publication_eligibility(url_or_domain: str) -> tuple[bool, str]:
    """Return explicit publication eligibility boolean and human-readable reason."""
    if not url_or_domain or not isinstance(url_or_domain, str):
        return False, "Empty or invalid URL/domain"

    target = url_or_domain.strip()
    if is_licensing_restricted(target):
        return False, "LICENSING RESTRICTION: Publisher is ineligible for automated publication without prior commercial license/syndication agreement (BBC, NDTV, The Indian Express, The Hindu, LiveMint)."

    if is_publication_authorized_url(target) or is_publication_authorized_domain(target):
        return True, "AUTHORIZED: Whitelisted and authorized for automated publication."

    if is_discovery_whitelisted_url(target) or is_discovery_whitelisted_domain(target):
        return False, "WHITELISTED BUT LICENSING INELIGIBLE: Whitelisted organization lacks automated publication license."

    return False, "UNAPPROVED SOURCE: Domain is not in the approved news organizations whitelist."


def get_canonical_domain(url: str) -> str | None:
    """Extract canonical domain string if approved for publication, otherwise None."""
    if not is_approved_url(url):
        return None
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        # Find the matching authorized root
        for authorized in sorted(PUBLICATION_AUTHORIZED_DOMAINS, key=len, reverse=True):
            if host == authorized or host.endswith("." + authorized):
                return authorized
        return host
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Topic Diversity Engine
# ---------------------------------------------------------------------------

KNOWN_ENTITIES = {
    "trump": ("trump", "donald trump"),
    "biden": ("biden", "joe biden"),
    "harris": ("harris", "kamala harris"),
    "modi": ("modi", "narendra modi"),
    "putin": ("putin", "vladimir putin"),
    "zelensky": ("zelensky", "zelenskiy", "volodymyr zelensky"),
    "netanyahu": ("netanyahu", "benjamin netanyahu"),
    "macron": ("macron", "emmanuel macron"),
    "starmer": ("starmer", "keir starmer"),
    "xi": ("xi jinping", "xi"),
    "trudeau": ("trudeau", "justin trudeau"),
    "carney": ("carney", "mark carney"),
    "musk": ("musk", "elon musk"),
    "obama": ("obama", "barack obama"),
    "sunak": ("sunak", "rishi sunak"),
    "scholz": ("scholz", "olaf scholz"),
}

COMMON_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "up", "about", "into", "over", "after", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "says", "said",
    "amid", "as", "it", "its", "that", "this", "these", "those", "will", "would", "shall",
    "should", "can", "could", "may", "might", "must", "than", "then", "now", "ahead",
    "touts", "urges", "calls", "plans", "probe", "claims", "condemns", "backs", "warns",
    "seeks", "eyes", "takes", "gives", "makes", "moves", "hits", "fuels", "faces", "new"
}


def extract_topic_entities(title: str) -> set[str]:
    """Extract recognized principal entities or substantive content words from a headline."""
    if not title or not isinstance(title, str):
        return set()

    lower = title.lower()
    entities = set()

    # 1. Match known political/world figures
    for canonical_name, aliases in KNOWN_ENTITIES.items():
        for alias in aliases:
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, lower):
                entities.add(canonical_name)
                break

    # 2. Extract substantive content words (stem-like nouns/verbs > 3 chars)
    words = re.findall(r"\b[a-z]{4,}\b", lower)
    substantive = {w for w in words if w not in COMMON_STOPWORDS}

    return entities or substantive


def compute_headline_similarity(title1: str, title2: str) -> float:
    """Compute Jaccard similarity over substantive words in two headlines."""
    words1 = {w for w in re.findall(r"\b[a-z]{4,}\b", (title1 or "").lower()) if w not in COMMON_STOPWORDS}
    words2 = {w for w in re.findall(r"\b[a-z]{4,}\b", (title2 or "").lower()) if w not in COMMON_STOPWORDS}
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)


def check_topic_diversity(
    candidate: str | dict,
    recent_posts: list[dict],
    max_same_topic: int = 2,
    window_size: int = 10
) -> tuple[bool, str]:
    """Check if candidate complies with the rolling topic diversity limit.

    Rule: At most `max_same_topic` (default 2) posts about the same principal person
    or substantially identical topic within the most recent `window_size` (default 10)
    confirmed published posts.

    Returns:
        (is_allowed: bool, reason: str)
    """
    if isinstance(candidate, dict):
        candidate_title = str(candidate.get("title") or candidate.get("headline") or "").strip()
    elif isinstance(candidate, str):
        candidate_title = candidate.strip()
    else:
        return False, "Candidate headline is empty or invalid"

    if not candidate_title:
        return False, "Candidate headline is empty or invalid"

    candidate_entities = extract_topic_entities(candidate_title)

    # Take the most recent published posts up to window_size
    confirmed_posts = [p for p in recent_posts if p.get("published") is not False]
    window = confirmed_posts[-window_size:] if len(confirmed_posts) >= window_size else confirmed_posts

    matched_posts = []

    for post in window:
        post_title = post.get("title") or post.get("headline") or ""
        if not post_title:
            continue

        # Check entity match
        post_entities = extract_topic_entities(post_title)
        shared_entities = candidate_entities.intersection(post_entities)

        # If shared entities include a known key figure (e.g. trump, biden, etc.)
        named_matches = {e for e in shared_entities if e in KNOWN_ENTITIES}
        if named_matches:
            matched_posts.append((post_title, f"shared entity '{list(named_matches)[0]}'"))
            continue

        # Check high lexical/substantive overlap (>50% Jaccard) for non-named story topics
        sim = compute_headline_similarity(candidate_title, post_title)
        if sim >= 0.50:
            matched_posts.append((post_title, f"substantive similarity ({sim:.0%})"))

    if len(matched_posts) >= max_same_topic:
        top_reason = matched_posts[0][1]
        msg = (
            f"Topic diversity limit reached: {len(matched_posts)} of the last {len(window)} posts "
            f"already cover this topic/person ({top_reason}). Limit is {max_same_topic}/{window_size}."
        )
        return False, msg

    return True, "Topic diversity within allowed threshold"

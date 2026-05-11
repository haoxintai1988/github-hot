#!/usr/bin/env python3
"""GitHub AI Hot Monitor - Main Data Pipeline

Two-stream architecture:
  Stream A (Hot List): GitHub Trending → AI filter → Top 5/10 →
                       HN Algolia + Reddit exact-name search → Score → Rank
  Stream B (Dark Horses): HN top stories + Reddit hot posts →
                          Reverse-extract GitHub refs → Low stars, high buzz → Treasure

Data sources (all real data, never fabricated):
  1. GitHub Trending page (HTML parse) - daily/weekly trending repos
  2. HN Firebase API - top stories reverse matching (dark horses)
  3. HN Algolia API - forward search by project name (hot list cross-validation)
  4. Reddit search API - forward search by project name (hot list cross-validation)
  5. Reddit hot posts - reverse GitHub ref extraction (dark horses)
  6. GitHub Issues API - activity signal
"""

import json
import logging
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from scorer import Scorer
from insight_generator import InsightGenerator
from water_mapper import WaterMapper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"User-Agent": "github-hot-ai-monitor/1.0"}
API_HEADERS = {**HEADERS, "Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    API_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# AI-related topics on GitHub
AI_TOPICS = [
    "ai-agent", "llm", "artificial-intelligence", "machine-learning",
    "deep-learning", "nlp", "natural-language-processing", "generative-ai",
    "gpt", "transformer", "rag", "vector-database", "llama", "openai",
    "chatgpt", "langchain", "agent", "multi-agent", "mcp",
    "text-to-image", "stable-diffusion", "multimodal", "speech-recognition",
    "computer-vision", "reinforcement-learning", "mlops",
]

# AI classification signals
AI_TOPIC_SIGNALS = {
    "ai", "artificial-intelligence", "llm", "large-language-model",
    "machine-learning", "deep-learning", "nlp", "natural-language-processing",
    "agent", "ai-agent", "gpt", "transformer", "rag", "vector-database",
    "llama", "openai", "chatgpt", "prompt-engineering", "langchain",
    "text-generation", "embeddings", "fine-tuning", "inference",
    "generative-ai", "multimodal", "computer-vision", "stable-diffusion",
    "mcp", "model-context-protocol",
}

AI_DESC_KEYWORDS = [
    r"\bai agent\b", r"\bllm\b", r"\blarge language model\b",
    r"\bmachine learning\b", r"\bdeep learning\b", r"\bneural\b",
    r"\btransformer\b", r"\brag\b", r"\bretrieval.augmented\b",
    r"\bprompt\b", r"\btoken\b", r"\bembedding\b", r"\bfine.tun",
    r"\binference\b", r"\bgenerative\b", r"\bgpt\b", r"\bchatgpt\b",
    r"\bllama\b", r"\bopenai\b", r"\banthropic\b", r"\bclaude\b",
    r"\bstable diffusion\b", r"\bmultimodal\b", r"\bagent\b",
    r"\bmcp\b", r"\bmodel context protocol\b",
]

AI_LANGUAGES = {"Python", "Jupyter Notebook", "Rust", "TypeScript"}

# Non-AI exclusions (even if they have some AI mentions)
NON_AI_EXCLUDE_PATTERNS = [
    r"pure.*frontend", r"css.*framework", r"ui.*component.*library",
]


# ── Helpers ────────────────────────────────────────────────────────────────

# Shared session for connection reuse (reduces SSL handshake overhead)
_SESSION = None

def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(HEADERS)
    return _SESSION


def api_get(url, params=None, headers=None, retries=3, ssl_no_verify=False):
    """GET with retry and backoff. Uses shared session for connection reuse."""
    session = _get_session()
    req_headers = {**HEADERS, **(headers or {})}
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, headers=req_headers, timeout=30, verify=not ssl_no_verify)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                wait = min(60 * (attempt + 1), 300)
                log.warning("Rate limited, waiting %ds", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.SSLError as e:
            if not ssl_no_verify:
                log.warning("SSL verify failed, retrying without verification: %s", e)
                return api_get(url, params=params, headers=headers, retries=retries, ssl_no_verify=True)
            wait = 2 ** attempt
            log.warning("SSL request failed (attempt %d/%d, retry in %ds): %s", attempt + 1, retries, wait, e)
            if attempt < retries - 1:
                time.sleep(wait)
        except requests.RequestException as e:
            wait = 2 ** attempt
            log.warning("Request failed (attempt %d/%d, retry in %ds): %s", attempt + 1, retries, wait, e)
            if attempt < retries - 1:
                time.sleep(wait)
    return None


def log_scale(value, base=10):
    """Log-scale compression for count values."""
    import math
    if value <= 0:
        return 0
    return math.log(value + 1, base)


# ── Source 1: GitHub Trending ──────────────────────────────────────────────

def parse_github_trending(since="daily"):
    """Scrape GitHub Trending page. Returns list of repo dicts."""
    url = f"https://github.com/trending"
    params = {"since": since} if since != "daily" else {}
    resp = api_get(url, params=params)
    if not resp:
        log.error("Failed to fetch GitHub Trending")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    repos = []

    for article in soup.find_all("article", class_="Box-row"):
        try:
            # Repo name
            h2 = article.find("h2", class_="h3")
            if not h2:
                continue
            a_tag = h2.find("a")
            if not a_tag:
                continue
            href = a_tag.get("href", "").strip()
            # href is like "/owner/repo"
            full_name = href.strip("/")
            parts = full_name.split("/")
            if len(parts) != 2:
                continue
            owner, name = parts

            # Description
            desc_p = article.find("p", class_="col-9")
            description = desc_p.text.strip() if desc_p else ""

            # Language
            lang_el = article.find("span", itemprop="programmingLanguage")
            language = lang_el.text.strip() if lang_el else ""

            # Stars and forks (from text like "123 stars today" or "1,234 stars this week")
            stars_text = ""
            forks_text = ""
            for span in article.find_all("span", class_="d-inline-block"):
                txt = span.text.strip()
                if "star" in txt.lower():
                    stars_text = txt
                elif "fork" in txt.lower():
                    forks_text = txt

            stars_added = _parse_count_string(stars_text)

            repos.append({
                "owner": owner,
                "name": name,
                "full_name": full_name,
                "description": description,
                "language": language,
                "stars_added": stars_added,
                "source": f"github-trending-{since}",
                "raw_stars_text": stars_text,
            })
        except Exception as e:
            log.debug("Error parsing trending repo: %s", e)
            continue

    log.info("GitHub Trending (%s): %d repos", since, len(repos))
    return repos


def _parse_count_string(text):
    """Extract number from strings like '1,234 stars today' or '567 stars this week'."""
    if not text:
        return 0
    match = re.search(r"([\d,]+)", text)
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))


def enrich_repo_details(repo):
    """Fetch full repo details from GitHub API to get topics, stars, etc."""
    url = f"https://api.github.com/repos/{repo['full_name']}"
    resp = api_get(url, headers=API_HEADERS)
    if not resp or resp.status_code != 200:
        return repo

    data = resp.json()
    repo["stars"] = data.get("stargazers_count", repo.get("stars", 0))
    repo["forks"] = data.get("forks_count", repo.get("forks", 0))
    repo["topics"] = data.get("topics", repo.get("topics", []))
    repo["description"] = data.get("description") or repo.get("description", "")
    repo["created_at"] = data.get("created_at", repo.get("created_at", ""))
    repo["updated_at"] = data.get("updated_at", repo.get("updated_at", ""))
    repo["language"] = data.get("language") or repo.get("language", "")
    return repo


# ── Source 3 & 4: Hacker News ──────────────────────────────────────────────

def hn_fetch_top_stories(limit=100):
    """Fetch top HN stories via Firebase API. Returns list of item dicts."""
    resp = api_get("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not resp:
        return []

    ids = resp.json()[:limit]
    stories = []
    for i, item_id in enumerate(ids):
        item_resp = api_get(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
        )
        if item_resp:
            item = item_resp.json()
            if item and item.get("type") == "story":
                stories.append(item)
        elif i == 0:
            log.warning("HN item fetch failing (network may be unstable), continuing...")
        time.sleep(0.25)

    log.info("HN Firebase: %d top stories fetched", len(stories))
    return stories


def hn_extract_github_refs(stories):
    """Extract GitHub repo references from HN story titles and URLs."""
    refs = []
    for story in stories:
        title = story.get("title", "")
        url = story.get("url") or ""
        score = story.get("score", 0)
        descendants = story.get("descendants", 0)
        story_id = story.get("id", 0)

        # Check URL for GitHub links
        gh_match = re.search(r"github\.com/([a-zA-Z0-9._-]+)/([a-zA-Z0-9._-]+)", url)
        if gh_match:
            refs.append({
                "full_name": f"{gh_match.group(1)}/{gh_match.group(2)}",
                "owner": gh_match.group(1),
                "name": gh_match.group(2),
                "hn_score": score,
                "hn_comments": descendants,
                "hn_title": title,
                "hn_url": f"https://news.ycombinator.com/item?id={story_id}",
                "source": "hn-firebase",
            })
            continue

        # Check title for Show HN: project names
        show_match = re.search(
            r"Show HN:.*?github\.com/([a-zA-Z0-9._-]+)/([a-zA-Z0-9._-]+)",
            title, re.IGNORECASE
        )
        if show_match:
            refs.append({
                "full_name": f"{show_match.group(1)}/{show_match.group(2)}",
                "owner": show_match.group(1),
                "name": show_match.group(2),
                "hn_score": score,
                "hn_comments": descendants,
                "hn_title": title,
                "hn_url": f"https://news.ycombinator.com/item?id={story_id}",
                "source": "hn-show",
            })

    log.info("HN: %d GitHub refs extracted from stories", len(refs))
    return refs


def hn_search_project(name, full_name, mode="daily"):
    """Search HN Algolia for mentions of a project.

    Uses repo name for distinctive names, full_name for common words.
    Filters to time window: 7 days daily, 30 days weekly.
    """
    # Distinctive names (has special chars or long enough) → search by name.
    # Common words / short strings → search by full_name to avoid noise.
    import re
    if re.search(r'[-_.]', name) or len(name) >= 8:
        query = name
    else:
        query = full_name

    url = "https://hn.algolia.com/api/v1/search"
    params = {"query": query, "tags": "story", "hitsPerPage": 10}
    resp = api_get(url, params=params, headers={"User-Agent": HEADERS["User-Agent"]})
    if not resp:
        return {"hn_points": 0, "hn_comments": 0, "hn_stories": []}

    data = resp.json()
    hits = data.get("hits", [])
    now = datetime.now(timezone.utc)
    max_days = 7 if mode == "daily" else 30

    stories = []
    max_points = 0
    max_comments = 0

    for hit in hits:
        created_at = hit.get("created_at", "")
        if created_at:
            try:
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if (now - created_dt).days > max_days:
                    continue
            except ValueError:
                pass

        pts = hit.get("points", 0) or 0
        comments = hit.get("num_comments", 0) or 0
        stories.append({
            "title": hit.get("title", ""),
            "points": pts,
            "comments": comments,
            "url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            "created_at": created_at,
        })
        max_points = max(max_points, pts)
        max_comments = max(max_comments, comments)

    return {
        "hn_points": max_points,
        "hn_comments": max_comments,
        "hn_stories": stories,
    }


# ── Source 5: Reddit ───────────────────────────────────────────────────────

REDDIT_SUBREDDITS = ["MachineLearning", "LocalLLaMA", "singularity"]


def _reddit_search_query(query, subreddits=None):
    """Search Reddit for a query string across subreddits. Returns (posts, max_ups, max_comments)."""
    if subreddits is None:
        subreddits = REDDIT_SUBREDDITS
    all_posts = []
    max_ups = 0
    max_comments = 0

    for subreddit in subreddits:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {"q": query, "sort": "relevance", "restrict_sr": "on", "limit": 10}
        headers = {**HEADERS, "User-Agent": "github-hot-ai/1.0 (research project)"}
        resp = api_get(url, params=params, headers=headers)
        if not resp:
            continue

        try:
            data = resp.json()
        except ValueError:
            continue

        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            ups = post.get("ups", 0) or 0
            comments = post.get("num_comments", 0) or 0
            all_posts.append({
                "subreddit": subreddit,
                "title": post.get("title", ""),
                "ups": ups,
                "comments": comments,
                "url": f"https://reddit.com{post.get('permalink', '')}",
                "created_utc": post.get("created_utc", 0),
            })
            max_ups = max(max_ups, ups)
            max_comments = max(max_comments, comments)

        time.sleep(0.5)

    return all_posts, max_ups, max_comments


def reddit_search_project(full_name):
    """Search Reddit for mentions of a project across AI subreddits.

    Uses a two-fallback strategy because Reddit's search API is unreliable:
    1. Search by full_name (e.g. "owner/repo")
    2. If empty, fall back to searching by repo name only
    3. If still empty, try "owner repo" (space-separated, no slash)
    """
    owner, _, name = full_name.partition("/")
    all_posts = []
    max_ups = 0
    max_comments = 0

    # Strategy 1: full_name search
    posts, ups, comments = _reddit_search_query(full_name)
    all_posts.extend(posts)
    max_ups = max(max_ups, ups)
    max_comments = max(max_comments, comments)

    # Strategy 2: repo name only (Reddit search tokenizes on / so full_name often fails)
    if not all_posts and len(name) >= 4:
        time.sleep(0.3)
        posts, ups, comments = _reddit_search_query(name)
        # Filter: only keep posts whose title/url mentions the repo
        posts = [p for p in posts if name.lower() in p["title"].lower() or name.lower() in p.get("url", "").lower()]
        all_posts.extend(posts)
        max_ups = max(max_ups, ups)
        max_comments = max(max_comments, comments)

    # Strategy 3: space-separated (some Reddit search versions handle this better)
    if not all_posts and owner:
        time.sleep(0.3)
        posts, ups, comments = _reddit_search_query(f"{owner} {name}")
        posts = [p for p in posts if name.lower() in p["title"].lower() or full_name.lower() in p.get("url", "").lower()]
        all_posts.extend(posts)
        max_ups = max(max_ups, ups)
        max_comments = max(max_comments, comments)

    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for p in all_posts:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            deduped.append(p)

    primary_subreddit = deduped[0]["subreddit"] if deduped else ""

    return {
        "reddit_ups": max_ups,
        "reddit_comments": max_comments,
        "reddit_posts": deduped,
        "reddit_subreddit": primary_subreddit,
    }


def reddit_search_top_ai_posts(limit=50):
    """Search each AI subreddit for top posts, extract GitHub refs."""
    refs = []
    for subreddit in REDDIT_SUBREDDITS:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json"
        params = {"limit": limit}
        headers = {**HEADERS, "User-Agent": "github-hot-ai/1.0 (research project)"}
        resp = api_get(url, params=params, headers=headers)
        if not resp:
            continue

        try:
            data = resp.json()
        except ValueError:
            continue

        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            title = post.get("title", "")
            text = post.get("selftext", "")
            post_url = post.get("url", "")
            combined = f"{title} {text} {post_url}"

            # Find GitHub URLs
            for match in re.finditer(
                r"github\.com/([a-zA-Z0-9._-]+)/([a-zA-Z0-9._-]+)",
                combined
            ):
                owner, name = match.group(1), match.group(2)
                # Skip common non-project paths
                if name in ("issues", "pull", "discussions", "releases", "wiki", "tree", "blob"):
                    continue
                refs.append({
                    "full_name": f"{owner}/{name}",
                    "owner": owner,
                    "name": name,
                    "reddit_ups": post.get("ups", 0),
                    "reddit_comments": post.get("num_comments", 0),
                    "reddit_subreddit": subreddit,
                    "reddit_title": title,
                    "reddit_url": f"https://reddit.com{post.get('permalink', '')}",
                    "source": "reddit-hot",
                })
        time.sleep(0.5)

    log.info("Reddit: %d GitHub refs extracted from hot posts", len(refs))
    return refs


# ── Source 6: GitHub Issues Activity ───────────────────────────────────────

def get_repo_issues_activity(full_name):
    """Get recent issues activity for a repo as a supplementary signal."""
    url = f"https://api.github.com/repos/{full_name}/issues"
    params = {"state": "open", "per_page": 10, "sort": "created"}
    resp = api_get(url, params=params, headers=API_HEADERS)
    if not resp:
        return {"recent_issues": 0, "avg_reactions": 0}

    issues = resp.json()
    if not isinstance(issues, list):
        return {"recent_issues": 0, "avg_reactions": 0}

    total_reactions = 0
    issue_count = 0
    now = datetime.now(timezone.utc)

    for issue in issues:
        if "pull_request" in issue:
            continue  # Skip PRs
        created = issue.get("created_at", "")
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                days_ago = (now - created_dt).days
                if days_ago <= 7:
                    issue_count += 1
                    reactions = issue.get("reactions", {})
                    total_reactions += sum([
                        reactions.get("+1", 0),
                        reactions.get("hooray", 0),
                        reactions.get("heart", 0),
                        reactions.get("rocket", 0),
                        reactions.get("eyes", 0),
                    ])
            except ValueError:
                pass

    avg_reactions = total_reactions / issue_count if issue_count > 0 else 0
    return {"recent_issues": issue_count, "avg_reactions": round(avg_reactions, 1)}


# ── AI Project Classification ──────────────────────────────────────────────

def is_ai_project(repo):
    """Multi-signal AI project classifier."""
    signals = 0
    reasons = []

    # 1. GitHub topics (highest weight)
    topics = {t.lower().replace(" ", "-") for t in repo.get("topics", [])}
    topic_hits = topics & AI_TOPIC_SIGNALS
    if topic_hits:
        signals += 3
        reasons.append(f"topics:{','.join(list(topic_hits)[:3])}")

    # 2. Description keywords
    desc = repo.get("description", "").lower()
    for kw in AI_DESC_KEYWORDS:
        if re.search(kw, desc, re.IGNORECASE):
            signals += 2
            clean_kw = kw.strip("\\b")
            reasons.append(f"desc:{clean_kw}")
            break

    # 3. Language signal
    lang = repo.get("language", "")
    if lang in AI_LANGUAGES and signals >= 1:
        signals += 1
        reasons.append(f"lang:{lang}")

    # 4. HN discussion context
    hn_title = repo.get("hn_title", "").lower()
    if hn_title:
        for kw in AI_DESC_KEYWORDS:
            if re.search(kw, hn_title, re.IGNORECASE):
                signals += 1
                clean_kw = kw.strip("\\b")
                reasons.append(f"hn:{clean_kw}")
                break

    # 5. Check non-AI exclusions
    for pat in NON_AI_EXCLUDE_PATTERNS:
        if re.search(pat, desc, re.IGNORECASE):
            signals -= 3
            reasons.append("excluded:non-ai")
            break

    # Lower threshold for pre-curated sources (GitHub Trending, HN, Reddit)
    source = repo.get("source", "")
    threshold = 2 if (
        source.startswith("github-trending")
        or source.startswith("hn-")
        or source.startswith("reddit-")
    ) else 3
    return signals >= threshold, reasons


# ── Main Pipeline ──────────────────────────────────────────────────────────

def _build_dark_horse_entry(repo, community_heat):
    """Build a dark horse insight entry from a repo dict."""
    return {
        "project": {
            "full_name": repo.get("full_name", ""),
            "name": repo.get("name", ""),
            "owner": repo.get("owner", ""),
            "description": repo.get("description", ""),
            "stars": repo.get("stars", 0),
            "language": repo.get("language", ""),
            "topics": repo.get("topics", []),
            "url": f"https://github.com/{repo.get('full_name', '')}",
        },
        "insight": (
            f"💎 {repo.get('name', '')} — "
            f"{repo.get('description', '')[:60]}，"
            f"仅 {repo.get('stars', 0)}⭐，"
            f"社区讨论热度 {community_heat:.0f} 分"
        ),
        "community_heat": community_heat,
        "hn_url": repo.get("hn_url", ""),
        "reddit_url": repo.get("reddit_url", ""),
    }


def run_pipeline(mode="daily"):
    """Run the two-stream pipeline.

    Stream A (Hot List): GitHub Trending → AI filter → Top 5/10 →
                         HN + Reddit exact-name search → Score → Rank
    Stream B (Dark Horses): HN + Reddit hot posts → extract GitHub refs →
                            enrich → filter low-star high-buzz → treasure list
    """
    log.info("=== Starting pipeline: mode=%s ===", mode)

    # ══════════════════════════════════════════════════════════════════════
    # Stream A: Hot List
    # ══════════════════════════════════════════════════════════════════════

    # A1. GitHub Trending
    trending = parse_github_trending(since=mode)
    if not trending:
        log.error("No trending repos found, aborting")
        return False
    log.info("A1: %d trending repos fetched", len(trending))

    # A2. Enrich trending repos with GitHub API (topics, total stars)
    if GITHUB_TOKEN:
        for i, repo in enumerate(trending):
            trending[i] = enrich_repo_details(repo)
            time.sleep(0.15)
        log.info("A2: enriched %d repos with API details", len(trending))
    else:
        for repo in trending:
            repo.setdefault("stars", 0)
            repo.setdefault("topics", [])
        log.info("A2: no token, skipped API enrichment")

    # A3. Filter to AI projects only
    ai_trending = []
    for repo in trending:
        is_ai, reasons = is_ai_project(repo)
        if is_ai:
            repo["ai_reasons"] = reasons
            ai_trending.append(repo)
        else:
            log.debug("Excluded non-AI: %s", repo.get("full_name"))
    log.info("A3: %d/%d AI-filtered", len(ai_trending), len(trending))

    # A4. Select top N by stars_added
    top_n = 5 if mode == "daily" else 10
    ai_trending.sort(key=lambda r: r.get("stars_added", 0), reverse=True)
    hot_list = ai_trending[:top_n]
    log.info("A4: top %d candidates selected", len(hot_list))

    # A5. HN + Reddit forward search for every candidate
    for repo in hot_list:
        # HN Algolia exact-name search
        hn_data = hn_search_project(repo["name"], repo["full_name"], mode=mode)
        repo["hn_points"] = hn_data.get("hn_points", 0)
        repo["hn_comments"] = hn_data.get("hn_comments", 0)
        repo["hn_stories"] = hn_data.get("hn_stories", [])
        if hn_data["hn_points"] > 0:
            repo["hn_score"] = hn_data["hn_points"]
            if hn_data["hn_stories"]:
                repo["hn_url"] = hn_data["hn_stories"][0]["url"]

        # Reddit exact-name search
        rd_data = reddit_search_project(repo["full_name"])
        repo["reddit_ups"] = rd_data.get("reddit_ups", 0)
        repo["reddit_comments"] = rd_data.get("reddit_comments", 0)
        repo["reddit_posts"] = rd_data.get("reddit_posts", [])
        if rd_data.get("reddit_ups", 0) > 0:
            repo["reddit_subreddit"] = rd_data.get("reddit_subreddit", "")
            if rd_data.get("reddit_posts"):
                repo["reddit_url"] = rd_data["reddit_posts"][0].get("url", "")

        log.info("A5: %s → HN=%dpts Reddit=%dups",
                 repo["full_name"], repo.get("hn_points", 0), repo.get("reddit_ups", 0))
        time.sleep(0.5)

    # A6. Issues activity (optional, needs token)
    if GITHUB_TOKEN:
        for repo in hot_list:
            repo["issues_activity"] = get_repo_issues_activity(repo["full_name"])

    # A7. Score and rank
    scorer = Scorer()
    for repo in hot_list:
        repo["scores"] = scorer.compute(repo)
        repo["heat_score"] = repo["scores"]["total"]

    hot_list.sort(key=lambda r: r["heat_score"], reverse=True)
    for i, repo in enumerate(hot_list):
        repo["rank"] = i + 1

    log.info("A7: scored and ranked. Top: %s (%.1f)",
             hot_list[0]["full_name"] if hot_list else "none",
             hot_list[0]["heat_score"] if hot_list else 0)

    # ══════════════════════════════════════════════════════════════════════
    # Stream B: Dark Horses (from HN + Reddit reverse extraction)
    # ══════════════════════════════════════════════════════════════════════

    # B1. HN top stories → extract GitHub refs
    hn_stories = hn_fetch_top_stories(limit=150)
    hn_refs = hn_extract_github_refs(hn_stories)

    # B2. Reddit hot posts → extract GitHub refs
    reddit_refs = reddit_search_top_ai_posts(limit=50)

    # B3. Merge HN + Reddit refs, track cross-platform signal
    dh_candidates = {}
    for r in hn_refs:
        key = r["full_name"].lower()
        dh_candidates[key] = dict(r)

    for r in reddit_refs:
        key = r["full_name"].lower()
        if key in dh_candidates:
            dh_candidates[key]["reddit_ups"] = r.get("reddit_ups", 0)
            dh_candidates[key]["reddit_subreddit"] = r.get("reddit_subreddit", "")
            dh_candidates[key]["reddit_url"] = r.get("reddit_url", "")
            dh_candidates[key]["has_both"] = True
        else:
            dh_candidates[key] = dict(r)

    log.info("B3: %d dark horse candidates (HN=%d, Reddit=%d)",
             len(dh_candidates), len(hn_refs), len(reddit_refs))

    # B4. Enrich candidates with GitHub API, AI-filter, treasure criteria
    hot_names = {r["full_name"].lower() for r in hot_list}
    dark_horses = []

    for key, candidate in dh_candidates.items():
        if key in hot_names:
            continue  # Already on the hot list, skip

        if GITHUB_TOKEN:
            candidate = enrich_repo_details(candidate)
            time.sleep(0.15)
        else:
            candidate.setdefault("stars", 0)
            candidate.setdefault("topics", [])

        # AI filter: Stream B candidates must pass the same classifier as Stream A.
        # HN/Reddit may discuss non-AI projects heavily; we exclude those.
        if not candidate.get("description"):
            candidate["description"] = candidate.get("hn_title", "") or candidate.get("reddit_title", "")
        is_ai, _ = is_ai_project(candidate)
        if not is_ai:
            log.debug("B4: excluded non-AI candidate %s", key)
            continue

        stars = candidate.get("stars", 999999)
        hn_heat = candidate.get("hn_score", 0) or candidate.get("hn_points", 0)
        reddit_heat = candidate.get("reddit_ups", 0)
        community_heat = max(hn_heat, reddit_heat)

        # Treasure threshold: community buzz > 25 AND stars < 5000
        if community_heat > 25 and stars < 5000:
            dark_horses.append(_build_dark_horse_entry(candidate, community_heat))

    dark_horses.sort(key=lambda r: r["community_heat"], reverse=True)
    dark_horses = dark_horses[:5]
    log.info("B4: %d dark horses identified", len(dark_horses))

    # B5. Backfill Reddit data from Stream B refs into Stream A hot list
    # Reddit search API is unreliable for forward search; Stream B's reverse
    # extraction (hot posts → GitHub refs) is a more reliable Reddit signal.
    # Cross-reference to fill gaps.
    for repo in hot_list:
        key = repo["full_name"].lower()
        if key in dh_candidates:
            candidate = dh_candidates[key]
            # Only backfill if Stream A forward search found nothing
            if repo.get("reddit_ups", 0) == 0 and candidate.get("reddit_ups", 0) > 0:
                repo["reddit_ups"] = candidate.get("reddit_ups", 0)
                repo["reddit_comments"] = candidate.get("reddit_comments", 0)
                repo["reddit_subreddit"] = candidate.get("reddit_subreddit", "")
                repo["reddit_url"] = candidate.get("reddit_url", "")
                repo["reddit_posts"] = [{
                    "subreddit": candidate.get("reddit_subreddit", ""),
                    "title": candidate.get("reddit_title", ""),
                    "ups": candidate.get("reddit_ups", 0),
                    "comments": candidate.get("reddit_comments", 0),
                    "url": candidate.get("reddit_url", ""),
                }]
                # Re-score with the new Reddit data
                repo["scores"] = scorer.compute(repo)
                repo["heat_score"] = repo["scores"]["total"]
                log.info("B5: backfilled Reddit data for %s (ups=%d)",
                         repo["full_name"], candidate.get("reddit_ups", 0))

    # Re-sort after backfill
    hot_list.sort(key=lambda r: r["heat_score"], reverse=True)
    for i, repo in enumerate(hot_list):
        repo["rank"] = i + 1

    # ══════════════════════════════════════════════════════════════════════
    # Generate insights, water recommendations, and save
    # ══════════════════════════════════════════════════════════════════════

    # Generate AI insights
    insight_gen = InsightGenerator()
    insights = insight_gen.generate(hot_list, mode=mode)
    insights["dark_horses"] = dark_horses  # Override with Stream B results

    # Generate water conservancy recommendations
    water_mapper = WaterMapper()
    water_insights = water_mapper.generate(hot_list, mode=mode)

    # Save outputs
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    output_key = "today" if mode == "daily" else "week"
    output_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "total_projects": len(hot_list),
        "projects": hot_list,
    }
    with open(DATA_DIR / f"{output_key}.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    with open(DATA_DIR / "insights.json", "w", encoding="utf-8") as f:
        json.dump(insights, f, ensure_ascii=False, indent=2)

    with open(DATA_DIR / "water_insights.json", "w", encoding="utf-8") as f:
        json.dump(water_insights, f, ensure_ascii=False, indent=2)

    meta = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_ai_projects": len(hot_list),
        "sources": {
            "github_trending": len(trending),
            "hn_refs": len(hn_refs),
            "reddit_refs": len(reddit_refs),
        },
        "dark_horses": len(dark_horses),
    }
    with open(DATA_DIR / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    log.info("=== Pipeline complete: %d hot + %d dark horses ===",
             len(hot_list), len(dark_horses))
    return True


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode not in ("daily", "weekly"):
        log.error("Mode must be 'daily' or 'weekly', got: %s", mode)
        sys.exit(1)
    success = run_pipeline(mode)
    sys.exit(0 if success else 1)

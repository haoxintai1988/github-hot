#!/usr/bin/env python3
"""GitHub AI Hot Monitor - Main Data Pipeline

Fetches trending AI projects from GitHub and cross-validates with
Hacker News and Reddit discussion heat. Outputs JSON data files.

Sources (all real data, never fabricated):
  1. GitHub Trending page (HTML parse) - daily/weekly trending repos
  2. GitHub Search API - AI topic/term search
  3. HN Firebase API - top stories reverse matching
  4. HN Algolia API - forward search for project mentions
  5. Reddit search API - 3 AI subreddits cross-validation
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
from bs4 import BeautifulSoup

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

# AI-related GitHub search queries
AI_SEARCH_QUERIES = [
    "ai agent framework stars:>50",
    "llm framework stars:>50",
    "rag framework stars:>50",
    "mcp server stars:>50",
    "machine learning tool stars:>50",
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


def api_get(url, params=None, headers=None, retries=3):
    """GET with retry and backoff. Uses shared session for connection reuse."""
    session = _get_session()
    req_headers = {**HEADERS, **(headers or {})}
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, headers=req_headers, timeout=30)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                wait = min(60 * (attempt + 1), 300)
                log.warning("Rate limited, waiting %ds", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
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


# ── Source 2: GitHub Search API ────────────────────────────────────────────

def github_search_ai_repos():
    """Search GitHub for AI repos by multiple queries. Returns list of repo dicts."""
    all_repos = []
    seen = set()

    for query in AI_SEARCH_QUERIES:
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": 15}
        resp = api_get(url, params=params, headers=API_HEADERS)
        if not resp:
            continue

        data = resp.json()
        for item in data.get("items", []):
            fid = item["full_name"]
            if fid in seen:
                continue
            seen.add(fid)

            all_repos.append({
                "owner": item["owner"]["login"],
                "name": item["name"],
                "full_name": fid,
                "description": item.get("description") or "",
                "language": item.get("language") or "",
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "topics": item.get("topics", []),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "url": item.get("html_url", ""),
                "source": "github-search",
            })
        time.sleep(1.5)  # Rate limit courtesy

    log.info("GitHub Search: %d unique repos", len(all_repos))
    return all_repos


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


def reddit_search_project(full_name):
    """Search Reddit for mentions of a project across AI subreddits."""
    all_posts = []
    max_ups = 0
    max_comments = 0

    for subreddit in REDDIT_SUBREDDITS:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {"q": full_name, "sort": "hot", "restrict_sr": "on", "limit": 5}
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

        time.sleep(0.5)  # Reddit rate limit courtesy

    # Deduplicate: same URL across subreddits
    seen_urls = set()
    deduped = []
    for p in all_posts:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            deduped.append(p)

    return {"reddit_ups": max_ups, "reddit_comments": max_comments, "reddit_posts": deduped}


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

    # Trending repos are pre-curated by GitHub's algorithm — lower bar
    source = repo.get("source", "")
    threshold = 2 if source.startswith("github-trending") else 3
    return signals >= threshold, reasons


# ── Main Pipeline ──────────────────────────────────────────────────────────

def merge_and_deduplicate(trending_repos, search_repos, hn_refs, reddit_refs):
    """Merge all sources, deduplicate by full_name, enrich with cross-source data."""
    merged = {}  # full_name -> repo dict

    def get_key(r):
        return r.get("full_name", f"{r.get('owner', '')}/{r.get('name', '')}").lower()

    # Add GitHub Trending repos
    for r in trending_repos:
        key = get_key(r)
        merged[key] = dict(r)

    # Add GitHub Search repos
    for r in search_repos:
        key = get_key(r)
        if key in merged:
            merged[key].update({k: v for k, v in r.items() if v})
        else:
            merged[key] = dict(r)

    # Add HN refs
    for r in hn_refs:
        key = get_key(r)
        if key in merged:
            merged[key]["hn_score"] = r.get("hn_score", 0)
            merged[key]["hn_comments"] = r.get("hn_comments", 0)
            merged[key]["hn_title"] = r.get("hn_title", "")
            merged[key]["hn_url"] = r.get("hn_url", "")
            if r.get("source"):
                merged[key]["hn_source"] = r["source"]
        else:
            merged[key] = dict(r)

    # Add Reddit refs
    for r in reddit_refs:
        key = get_key(r)
        if key in merged:
            merged[key]["reddit_ups"] = max(
                merged[key].get("reddit_ups", 0), r.get("reddit_ups", 0)
            )
            merged[key]["reddit_subreddit"] = r.get("reddit_subreddit", "")
        else:
            merged[key] = dict(r)

    return list(merged.values())


def run_pipeline(mode="daily"):
    """Run the full data pipeline for the given mode (daily/weekly)."""
    log.info("=== Starting pipeline: mode=%s ===", mode)

    # 1. Fetch GitHub Trending
    trending = parse_github_trending(since=mode)
    if not trending:
        log.error("No trending repos found, aborting")
        return False

    # 2. Fetch GitHub Search results
    search_repos = github_search_ai_repos()

    # 3. Fetch HN top stories and extract GitHub refs (Path A)
    hn_stories = hn_fetch_top_stories(limit=150)
    hn_refs = hn_extract_github_refs(hn_stories)

    # 4. Fetch Reddit top posts and extract GitHub refs
    reddit_refs = reddit_search_top_ai_posts(limit=50)

    # 5. Merge all sources
    all_repos = merge_and_deduplicate(trending, search_repos, hn_refs, reddit_refs)
    log.info("Merged: %d unique repos before AI filter", len(all_repos))

    # 6. Enrich repos with full API details
    # Without GITHUB_TOKEN, skip this entirely — too rate-limited.
    # Trending page already gives us stars_added + description + language.
    if GITHUB_TOKEN:
        for i, repo in enumerate(all_repos):
            source = repo.get("source", "")
            if source in {"github-trending-daily", "github-trending-weekly", "hn-firebase", "hn-show"} or not repo.get("stars"):
                repo = enrich_repo_details(repo)
                all_repos[i] = repo
            time.sleep(0.15)
    else:
        log.info("No GITHUB_TOKEN: skipping GitHub API enrichment (rate limit: 60/hr)")
        # For trending repos, stars_added is already set from page parsing
        # For other sources, set total stars to 0 if unknown (honesty over fabrication)
        for repo in all_repos:
            if not repo.get("stars"):
                repo["stars"] = 0

    # 7. AI classification
    ai_repos = []
    for repo in all_repos:
        is_ai, reasons = is_ai_project(repo)
        if is_ai:
            repo["ai_reasons"] = reasons
            ai_repos.append(repo)
        else:
            log.debug("Excluded non-AI: %s (reasons: %s)", repo.get("full_name"), reasons)

    log.info("AI filter: %d/%d repos passed", len(ai_repos), len(all_repos))

    # 8. HN forward search — only for top 25 candidates (no-token optimization)
    # Sort by a rough heuristic first: stars_added + existing hn_score
    ai_repos.sort(key=lambda r: r.get("stars_added", 0) + r.get("hn_score", 0) * 5, reverse=True)
    hn_search_count = 25 if not GITHUB_TOKEN else len(ai_repos)
    for i, repo in enumerate(ai_repos):
        if i >= hn_search_count:
            break
        if not repo.get("hn_score"):
            hn_data = hn_search_project(repo["name"], repo["full_name"], mode=mode)
            repo["hn_points"] = hn_data.get("hn_points", 0)
            repo["hn_comments"] = max(
                repo.get("hn_comments", 0), hn_data.get("hn_comments", 0)
            )
            repo["hn_stories"] = hn_data.get("hn_stories", [])
            if hn_data["hn_points"] > 0:
                repo["hn_score"] = max(
                    repo.get("hn_score", 0), hn_data["hn_points"]
                )
                if not repo.get("hn_url") and hn_data["hn_stories"]:
                    repo["hn_url"] = hn_data["hn_stories"][0]["url"]
        time.sleep(0.2)

    # 9. Reddit forward search removed — noisy results, constant 429 rate limiting
    # Reddit signal comes from reddit_search_top_ai_posts() (hot posts extraction) only

    # 9. GitHub Issues activity — needs token, skip entirely otherwise
    if GITHUB_TOKEN:
        for repo in ai_repos[:30]:
            activity = get_repo_issues_activity(repo["full_name"])
            repo["issues_activity"] = activity
    else:
        log.info("No GITHUB_TOKEN: skipping Issues activity (needs API)")

    # 10. Score all projects
    scorer = Scorer()
    for repo in ai_repos:
        repo["scores"] = scorer.compute(repo)
        repo["heat_score"] = repo["scores"]["total"]

    # Sort by heat score descending
    ai_repos.sort(key=lambda r: r["heat_score"], reverse=True)

    # 11. Generate insights
    insight_gen = InsightGenerator()
    insights = insight_gen.generate(ai_repos, mode=mode)

    # 12. Generate water conservancy recommendations
    water_mapper = WaterMapper()
    water_insights = water_mapper.generate(ai_repos, mode=mode)

    # 13. Save output
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    output_key = "today" if mode == "daily" else "week"
    output_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "total_projects": len(ai_repos),
        "projects": ai_repos,
    }
    with open(DATA_DIR / f"{output_key}.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    with open(DATA_DIR / "insights.json", "w", encoding="utf-8") as f:
        json.dump(insights, f, ensure_ascii=False, indent=2)

    with open(DATA_DIR / "water_insights.json", "w", encoding="utf-8") as f:
        json.dump(water_insights, f, ensure_ascii=False, indent=2)

    # Meta
    meta = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_ai_projects": len(ai_repos),
        "sources": {
            "github_trending": len(trending),
            "github_search": len(search_repos),
            "hn_refs": len(hn_refs),
            "reddit_refs": len(reddit_refs),
        },
    }
    with open(DATA_DIR / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    log.info("=== Pipeline complete: %d AI projects saved ===", len(ai_repos))
    return True


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode not in ("daily", "weekly"):
        log.error("Mode must be 'daily' or 'weekly', got: %s", mode)
        sys.exit(1)
    success = run_pipeline(mode)
    sys.exit(0 if success else 1)

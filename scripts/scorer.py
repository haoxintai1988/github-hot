#!/usr/bin/env python3
"""Four-dimensional scoring algorithm for AI project heat ranking.

Dimensions:
  1. Stars growth (0.40) - log-compressed new stars
  2. HN heat (0.25) - log-compressed points + comments
  3. Reddit heat (0.20) - log-compressed ups + comments
  4. Topic potential (0.15) - treasure signal + issues activity
"""

import math
from typing import Dict


class Scorer:
    def __init__(self):
        self.weights = {
            "stars_growth": 0.40,
            "hn_heat": 0.25,
            "reddit_heat": 0.20,
            "topic_potential": 0.15,
        }

    def compute(self, repo: dict) -> Dict[str, float]:
        """Compute all dimension scores and total heat score for a repo."""
        scores = {
            "stars_growth": self._stars_growth_score(repo),
            "hn_heat": self._hn_heat_score(repo),
            "reddit_heat": self._reddit_heat_score(repo),
            "topic_potential": self._topic_potential_score(repo),
        }
        scores["total"] = round(
            sum(scores[k] * self.weights[k] for k in self.weights), 1
        )
        scores["is_treasure"] = self._is_treasure(repo, scores)
        return scores

    def _log_norm(self, value: float, cap: float = 10000) -> float:
        """Log-compress and normalize to 0-100 scale."""
        if value <= 0:
            return 0
        compressed = math.log(value + 1, 10)
        cap_compressed = math.log(cap + 1, 10)
        return min(100, (compressed / cap_compressed) * 100)

    def _stars_growth_score(self, repo: dict) -> float:
        """Stars growth velocity score.

        Uses stars_added from trending page (primary) or estimates from total stars
        for projects found via other sources.
        """
        stars_added = repo.get("stars_added", 0)
        total_stars = repo.get("stars", 0)

        if stars_added > 0:
            # Direct growth data from trending page
            return self._log_norm(stars_added, cap=5000)

        if total_stars > 0:
            # For non-trending repos, total stars gives a baseline
            base = self._log_norm(total_stars, cap=100000) * 0.3
            return min(100, base)

        return 10  # Floor for repos we found but have no star data

    def _hn_heat_score(self, repo: dict) -> float:
        """HN discussion heat - combines score and comment count."""
        hn_score = repo.get("hn_score", 0) or repo.get("hn_points", 0)
        hn_comments = repo.get("hn_comments", 0)

        if hn_score <= 0 and hn_comments <= 0:
            return 0

        points_score = self._log_norm(hn_score, cap=2000)
        comments_score = self._log_norm(hn_comments, cap=500)

        return points_score * 0.6 + comments_score * 0.4

    def _reddit_heat_score(self, repo: dict) -> float:
        """Reddit discussion heat across three subreddits."""
        ups = repo.get("reddit_ups", 0)
        comments = repo.get("reddit_comments", 0)

        if ups <= 0 and comments <= 0:
            return 0

        ups_score = self._log_norm(ups, cap=3000)
        comments_score = self._log_norm(comments, cap=300)

        return ups_score * 0.6 + comments_score * 0.4

    def _topic_potential_score(self, repo: dict) -> float:
        """Topic potential - rewards treasure projects and signals early discovery.

        Treasure signal: high community discussion but low stars = undervalued project.
        Also factors in issues activity as a sign of real-world usage.
        """
        score = 0

        # Cross-validation: project discussed on HN AND Reddit = genuine multi-platform heat
        has_hn = repo.get("hn_score", 0) > 0 or repo.get("hn_points", 0) > 0
        has_reddit = repo.get("reddit_ups", 0) > 0
        if has_hn and has_reddit:
            score += 15

        # Treasure signal bonus
        hn_score = repo.get("hn_score", 0)
        reddit_ups = repo.get("reddit_ups", 0)
        total_stars = repo.get("stars", 999999)
        community_heat = max(
            self._hn_heat_score(repo),
            self._reddit_heat_score(repo),
        )

        if community_heat > 40 and total_stars < 5000:
            # Projects with community buzz but relatively low stars
            # The bigger the gap, the stronger the treasure signal
            star_level = self._log_norm(total_stars, cap=5000)
            heat_level = community_heat
            if heat_level > star_level:
                score += min(60, (heat_level - star_level) * 0.8)

        # Issues activity bonus
        issues_activity = repo.get("issues_activity", {})
        if issues_activity:
            recent = issues_activity.get("recent_issues", 0)
            avg_reactions = issues_activity.get("avg_reactions", 0)
            if recent >= 5:
                score += min(20, recent * 2)
            if avg_reactions >= 3:
                score += min(15, avg_reactions * 3)

        # AI topic richness bonus
        topics = repo.get("topics", [])
        ai_topic_count = len([
            t for t in topics
            if t.lower() in {
                "ai", "llm", "agent", "rag", "machine-learning",
                "deep-learning", "nlp", "generative-ai",
            }
        ])
        score += min(10, ai_topic_count * 3)

        return min(100, score)

    def _is_treasure(self, repo: dict, scores: dict) -> bool:
        """Determine if this is a 'treasure project' - high buzz, low stars."""
        community_heat = max(scores["hn_heat"], scores["reddit_heat"])
        total_stars = repo.get("stars", 999999)
        return community_heat > 40 and total_stars < 2000

#!/usr/bin/env python3
"""AI Insights Generator - curates editorial highlights from scraped data.

Produces three sections:
  1. Today's Headline (#1 project with why-it-matters)
  2. Dark Horses (treasure projects with high buzz but low stars)
  3. Trend Signals (keyword clustering across top projects)
"""

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List


class InsightGenerator:
    # Topic clusters for trend detection
    TREND_CLUSTERS = {
        "Agent 框架 / MCP 协议": {
            "keywords": ["agent", "mcp", "model-context-protocol", "workflow",
                        "multi-agent", "ai-agent", "agentic"],
            "template": "Agent 框架与 MCP 协议类项目集中爆发，AI 工具互联互通和自主任务执行成为当前焦点",
        },
        "多模态 AI": {
            "keywords": ["multimodal", "vision-language", "text-to-image",
                        "image-text", "video", "speech", "audio"],
            "template": "多模态 AI 项目持续升温，视觉-语言理解和生成能力持续突破",
        },
        "LLM 推理与部署": {
            "keywords": ["inference", "quantization", "llama", "gguf", "vllm",
                        "tensorrt", "onnx", "edge", "deploy"],
            "template": "LLM 推理优化与本地部署工具集中涌现，模型效率成为工程焦点",
        },
        "RAG 与知识检索": {
            "keywords": ["rag", "vector-database", "embedding", "knowledge-graph",
                        "retrieval", "chunking", "semantic-search"],
            "template": "RAG 与知识检索技术持续演进，企业级知识管理需求驱动创新",
        },
        "AI 编程与开发工具": {
            "keywords": ["code", "copilot", "ide", "developer-tools", "sdk",
                        "cli", "programming", "llm-coding"],
            "template": "AI 编程工具生态加速成熟，开发者工作流正在被重新定义",
        },
        "开源模型发布": {
            "keywords": ["model", "checkpoint", "weights", "fine-tuned",
                        "pretrained", "foundation-model", "release"],
            "template": "新一批开源模型/权重集中发布，模型能力普惠化趋势明显",
        },
    }

    def generate(self, projects: List[dict], mode: str = "daily") -> dict:
        """Generate AI insights from ranked project list."""
        if not projects:
            return self._empty_result(mode)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "headline": self._generate_headline(projects, mode),
            "dark_horses": self._generate_dark_horses(projects),
            "trend_signals": self._generate_trend_signals(projects),
        }

    def _generate_headline(self, projects: List[dict], mode: str = "daily") -> dict:
        """Generate today's headline from the #1 project."""
        top = projects[0]
        scores = top.get("scores", {})

        # Mode-aware label for stars added
        star_label = "单日新增" if mode == "daily" else "本周新增"

        # Build the "why it's hot" sentence
        reasons = []
        if top.get("stars_added", 0) > 100:
            reasons.append(f"{star_label} {top['stars_added']}⭐")
        elif top.get("stars", 0) > 5000:
            reasons.append(f"累计 {top.get('stars', 0):,}⭐")

        if scores.get("hn_heat", 0) > 30:
            hn_pts = top.get("hn_score", top.get("hn_points", 0))
            if hn_pts > 0:
                reasons.append(f"HN {hn_pts} 分热议")

        if scores.get("reddit_heat", 0) > 30:
            sub = top.get("reddit_subreddit", "")
            if sub:
                reasons.append(f"r/{sub} 热议")

        if top.get("topics"):
            top_topics = top["topics"][:3]
            reasons.append(f"方向：{'/'.join(top_topics)}")

        time_word = "今日" if mode == "daily" else "本周"
        why = "、".join(reasons) if reasons else f"{top.get('language', '')} 项目引发关注"

        return {
            "project": {
                "full_name": top.get("full_name", ""),
                "name": top.get("name", ""),
                "owner": top.get("owner", ""),
                "description": top.get("description", ""),
                "stars": top.get("stars", 0),
                "stars_added": top.get("stars_added", 0),
                "heat_score": top.get("heat_score", 0),
                "url": top.get("url", f"https://github.com/{top.get('full_name', '')}"),
                "topics": top.get("topics", [])[:5],
                "language": top.get("language", ""),
                "is_treasure": scores.get("is_treasure", False),
            },
            "why_hot": f"🔥 {top.get('name', top.get('full_name', ''))} {time_word}爆火：{why}",
            "hn_url": top.get("hn_url", ""),
            "reddit_url": top.get("reddit_posts", [{}])[0].get("url", "") if top.get("reddit_posts") else "",
        }

    def _generate_dark_horses(self, projects: List[dict]) -> List[dict]:
        """Find treasure projects: high community buzz, low GitHub stars."""
        dark_horses = []

        for p in projects:
            scores = p.get("scores", {})
            if not scores.get("is_treasure"):
                continue

            community_max = max(scores.get("hn_heat", 0), scores.get("reddit_heat", 0))
            if community_max < 40:
                continue

            stars = p.get("stars", 0)
            if stars >= 2000:
                continue

            # Determine why it's interesting
            signals = []
            if scores.get("hn_heat", 0) >= 40:
                hn_pts = p.get("hn_score", p.get("hn_points", 0))
                signals.append(f"HN 讨论热度 {hn_pts} 分")
            if scores.get("reddit_heat", 0) >= 40:
                sub = p.get("reddit_subreddit", "MachineLearning")
                signals.append(f"r/{sub} 热议中")
            if p.get("issues_activity", {}).get("recent_issues", 0) >= 5:
                signals.append("Issues 活跃，早期用户深度使用中")

            dark_horses.append({
                "project": {
                    "full_name": p.get("full_name", ""),
                    "name": p.get("name", ""),
                    "owner": p.get("owner", ""),
                    "description": p.get("description", ""),
                    "stars": stars,
                    "language": p.get("language", ""),
                    "topics": p.get("topics", [])[:5],
                    "url": p.get("url", f"https://github.com/{p.get('full_name', '')}"),
                },
                "insight": f"💎 {p.get('name', '')} — {p.get('description', '')[:80]}，仅 {stars}⭐，{'、'.join(signals)}",
                "community_heat": community_max,
                "hn_url": p.get("hn_url", ""),
                "reddit_url": p.get("reddit_posts", [{}])[0].get("url", "") if p.get("reddit_posts") else "",
            })

        # Sort by community heat descending, take top 5
        dark_horses.sort(key=lambda d: d["community_heat"], reverse=True)
        return dark_horses[:5]

    def _generate_trend_signals(self, projects: List[dict]) -> List[dict]:
        """Detect emerging trends via keyword co-occurrence clustering."""
        # Collect all topics and keywords from top projects
        all_topics = []
        for p in projects[:30]:
            all_topics.extend(p.get("topics", []))
            all_topics.append(p.get("language", ""))
            desc = p.get("description", "")
            # Extract topic-like words from description
            for word in desc.lower().split():
                all_topics.append(word.strip(".,;:()[]"))

        topic_counter = Counter(t.lower().replace(" ", "-") for t in all_topics if t)

        # Match against trend clusters
        signals = []
        for cluster_name, config in self.TREND_CLUSTERS.items():
            keyword_matches = sum(
                topic_counter.get(kw, 0) for kw in config["keywords"]
            )
            if keyword_matches >= 3:  # At least 3 keyword occurrences
                # Find representative projects for this trend
                reps = []
                for p in projects[:20]:
                    p_topics = {t.lower() for t in p.get("topics", [])}
                    p_desc = p.get("description", "").lower()
                    if any(
                        kw in p_topics or kw in p_desc
                        for kw in config["keywords"]
                    ):
                        reps.append(p.get("name", p.get("full_name", "")))
                        if len(reps) >= 3:
                            break

                signals.append({
                    "trend": cluster_name,
                    "description": config["template"],
                    "representative_projects": reps,
                    "match_count": keyword_matches,
                })

        # Sort by match count, take top 3
        signals.sort(key=lambda s: s["match_count"], reverse=True)
        return signals[:3]

    def _empty_result(self, mode: str) -> dict:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "headline": None,
            "dark_horses": [],
            "trend_signals": [],
        }

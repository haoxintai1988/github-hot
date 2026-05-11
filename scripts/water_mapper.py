#!/usr/bin/env python3
"""Water Conservancy Domain Mapper

Maps trending AI projects to water conservancy applications via a
pre-defined rule table (domain knowledge, hardcoded for accuracy).
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

# ── Mapping Table ──────────────────────────────────────────────────────────
# AI tech direction → water conservancy scenarios

MAPPING_TABLE = [
    {
        "tech_direction": "计算机视觉",
        "strong": [
            # High-specificity terms — one hit is enough
            "computer-vision", "object-detection", "yolo", "segmentation",
            "image-classification", "image-recognition", "image-segmentation",
            "pose-estimation", "ocr", "optical-character",
        ],
        "weak": [
            # Lower-specificity terms — need 2+ hits across strong+weak
            "opencv", "visual", "detection", "tracking",
            "convolutional", "cnn", "resnet", "vision-transformer",
        ],
        "water_scenarios": [
            "河道漂浮物智能识别",
            "水位标尺自动读数",
            "堤坝裂缝/渗漏视觉检测",
            "水库周界入侵智能识别",
            "闸门启闭状态视频监控",
        ],
        "suggestion_template": (
            "可引入 {projects} 提升水利视觉监控精度。"
            "{direction} 方向当前发展迅速，建议在水库/河道重点监控点部署，"
            "实现漂浮物自动识别和告警，替代人工巡检，提高异常发现时效性。"
        ),
    },
    {
        "tech_direction": "LLM / RAG 知识库",
        "strong": [
            "llm", "rag", "large-language-model", "langchain",
            "retrieval-augmented", "retrieval-augmented-generation",
            "knowledge-base", "vector-database", "embedding",
            "chatgpt", "openai", "claude", "llama",
        ],
        "weak": [
            "chatbot", "qa", "summarization", "text-generation",
            "prompt-engineering", "fine-tuning", "token",
            "generative-ai", "nlp", "natural-language",
        ],
        "water_scenarios": [
            "水利知识库智能问答",
            "防汛预案自动生成",
            "水利工程报告辅助编写",
            "水务业务智能客服",
            "水利法规/标准合规审查",
        ],
        "suggestion_template": (
            "可基于 {projects} 构建水利领域知识问答系统。"
            "{direction} 技术日趋成熟，建议将水利工程规范、防汛预案、历史案例等"
            "文档结构化后接入 RAG 系统，实现业务知识即时检索和方案生成。"
        ),
    },
    {
        "tech_direction": "Agent 智能体框架",
        "strong": [
            "ai-agent", "agent", "multi-agent", "agentic",
            "mcp", "model-context-protocol",
        ],
        "weak": [
            "workflow", "orchestration", "tool-use", "swarm",
            "autonomous", "agent-framework",
        ],
        "water_scenarios": [
            "水利多智能体协同调度",
            "防汛应急自动响应流程",
            "闸泵阀多系统联动控制",
            "水库巡检 Agent 自动化",
            "跨部门数据协同调度",
        ],
        "suggestion_template": (
            "可参考 {projects} 架构设计水利多智能体协同系统。"
            "{direction} 是当前最大热点，水利领域「闸泵阀联动」「防汛应急响应」"
            "天然适配多 Agent 协同架构。建议先从单一场景 Agent 做起，"
            "逐步构建跨系统的智能体协同调度体系。"
        ),
    },
    {
        "tech_direction": "时间序列预测",
        "strong": [
            "time-series", "forecasting", "prophet", "anomaly-detection",
            "lstm", "arima", "time-series-forecasting",
        ],
        "weak": [
            "prediction", "regression", "temporal", "sequence",
            "sensor", "iot",
        ],
        "water_scenarios": [
            "水文站流量预测",
            "降雨径流预报",
            "水库入库流量预测",
            "城市内涝风险预警",
            "地下水水位趋势预测",
        ],
        "suggestion_template": (
            "可借鉴 {projects} 提升水文预报模型精度。"
            "{direction} 方向的新模型架构可直接应用于水库入库流量预测、"
            "城市内涝预警等场景，建议对比现有 LSTM 模型评估精度提升。"
        ),
    },
    {
        "tech_direction": "边缘端 AI 部署",
        "strong": [
            "edge", "onnx", "tensorrt", "gguf", "edge-ai",
            "tinyml", "on-device", "embedded",
            "quantization", "quantized",
        ],
        "weak": [
            "tiny", "lightweight", "efficient",
        ],
        "water_scenarios": [
            "水库边缘侧 AI 推理",
            "闸泵站离线智能控制",
            "野外低功耗 AI 设备",
            "水利传感器智能预处理",
            "偏远站点自主运行",
        ],
        "suggestion_template": (
            "可用 {projects} 实现水利边缘端轻量化 AI 部署。"
            "{direction} 技术使 AI 模型可部署到水利现场的边缘设备上，"
            "无需依赖网络连接即可运行推理，适合水库、闸泵站等野外站点。"
        ),
    },
    {
        "tech_direction": "多模态 AI",
        "strong": [
            "multimodal", "vision-language", "visual-question-answering",
            "clip", "blip", "cross-modal", "image-text",
            "video-understanding", "text-to-image", "grounding",
        ],
        "weak": [
            "video", "speech", "audio", "image-captioning",
        ],
        "water_scenarios": [
            "遥感影像 + 文本联合分析",
            "无人机巡检影像自动解译",
            "水利工程图纸 AI 理解",
            "多源水利数据融合分析",
            "视频监控智能语义检索",
        ],
        "suggestion_template": (
            "可结合 {projects} 增强水利多源数据融合分析能力。"
            "{direction} 技术能同时理解遥感影像、视频监控画面和文本报告，"
            "实现图文互查、影像问答，提升防汛会商的信息聚合效率。"
        ),
    },
    {
        "tech_direction": "数据处理 / 数据治理",
        "strong": [
            "etl", "spark", "flink", "dataframe",
            "data-warehouse", "data-lake", "data-pipeline",
            "streaming", "real-time",
        ],
        "weak": [
            "warehouse", "lake", "catalog", "schema",
            "parquet", "arrow", "duckdb",
        ],
        "water_scenarios": [
            "水利多源异构数据治理",
            "实时水文数据流处理",
            "跨部门数据融合",
            "水利数据仓库建设",
            "历史水文数据清洗/标注",
        ],
        "suggestion_template": (
            "可参考 {projects} 优化水利数据治理流水线。"
            "{direction} 工具可加速水利多源数据（水雨情、工情、气象、遥感）"
            "的汇聚治理，为上层 AI 应用提供高质量数据底座。"
        ),
    },
]

# Summary templates by mode
SUMMARY_TEMPLATES = {
    "daily": "今日 AI 热点对水利行业的启示：{directions}。建议重点关注 {top_rec}。",
    "weekly": "本周 AI 热点对水利行业的启示：{directions}。{top_rec} 方向值得深入调研，可纳入下阶段技术选型评估。",
}


class WaterMapper:
    def generate(self, projects: List[dict], mode: str = "daily") -> dict:
        """Map trending AI projects to water conservancy recommendations."""
        if not projects:
            return self._empty_result(mode)

        # Step 1: Classify each project into tech directions
        direction_projects = defaultdict(list)

        for p in projects:
            matched = self._match_project(p)
            for direction in matched:
                direction_projects[direction].append(p)

        # Step 2: Generate recommendations for each direction with matches
        recommendations = []
        for mapping in MAPPING_TABLE:
            tech_dir = mapping["tech_direction"]
            dir_projects = direction_projects.get(tech_dir, [])
            if not dir_projects:
                continue

            # Take top 2-3 projects as representatives
            top_projects = sorted(
                dir_projects,
                key=lambda p: p.get("heat_score", 0),
                reverse=True,
            )[:3]

            project_names = [p.get("name", "") for p in top_projects]
            projects_str = "、".join(project_names)

            suggestion = mapping["suggestion_template"].format(
                projects=projects_str,
                direction=tech_dir,
            )

            recommendations.append({
                "tech_direction": tech_dir,
                "keywords": mapping["keywords"][:5],
                "water_scenarios": mapping["water_scenarios"],
                "hot_projects": [
                    {
                        "name": p.get("name", ""),
                        "full_name": p.get("full_name", ""),
                        "description": p.get("description", "")[:120],
                        "stars": p.get("stars", 0),
                        "heat_score": p.get("heat_score", 0),
                        "url": p.get("url", f"https://github.com/{p.get('full_name', '')}"),
                    }
                    for p in top_projects
                ],
                "suggestion": suggestion,
            })

        # Sort by total heat of projects in each direction
        recommendations.sort(
            key=lambda r: sum(p["heat_score"] for p in r["hot_projects"]),
            reverse=True,
        )

        # Step 3: Generate summary
        top_directions = [r["tech_direction"] for r in recommendations[:3]]
        top_rec = recommendations[0]["tech_direction"] if recommendations else "Agent 智能体框架"

        summary = SUMMARY_TEMPLATES.get(mode, SUMMARY_TEMPLATES["daily"]).format(
            directions="、".join(top_directions) if top_directions else "暂无显著热点",
            top_rec=top_rec,
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "summary": summary,
            "recommendations": recommendations,
        }

    def _match_project(self, project: dict) -> List[str]:
        """Match a project to tech directions using strong/weak keyword scoring.

        Uses token-boundary matching to avoid substring collisions
        (e.g. "edge" falsely matching "knowledge").

        - 1+ strong keyword match → direction matches
        - 2+ combined (strong + weak) keyword matches → direction matches
        - Otherwise → no match
        """
        import re

        desc = project.get("description", "").lower()
        name = project.get("name", "").lower()

        # GitHub topics are hyphen-separated slugs; keep them as-is for
        # exact matching (e.g. "computer-vision" ↔ "computer-vision")
        raw_topics = [t.lower() for t in project.get("topics", [])]
        topic_set = set(raw_topics)

        # Tokenize description + name into word tokens for safe matching
        all_text = f"{name} {desc} {' '.join(raw_topics)}"
        tokens = set(re.split(r'[^a-z0-9]', all_text))
        tokens.discard('')

        matched = []
        for mapping in MAPPING_TABLE:
            strong_hits = 0
            weak_hits = 0

            for kw in mapping.get("strong", []):
                kw_lower = kw.lower()
                # Exact match against topic slugs, token match against text
                if kw_lower in topic_set or kw_lower in tokens:
                    strong_hits += 1

            for kw in mapping.get("weak", []):
                kw_lower = kw.lower()
                if kw_lower in topic_set or kw_lower in tokens:
                    weak_hits += 1

            if strong_hits >= 1 or (strong_hits + weak_hits) >= 2:
                matched.append(mapping["tech_direction"])

        return matched

    def _empty_result(self, mode: str) -> dict:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "summary": "暂无足够数据生成水利行业建议",
            "recommendations": [],
        }

# GitHub AI 热点监控

监控 GitHub 上火热 AI 开源项目的网页。通过 **stars 增速** + **Hacker News** + **Reddit** 三个维度交叉验证，发现当下最火的 AI 项目和提前发现"宝藏项目"。

## 功能

- **今日最热 / 一周最热** — 双视图切换
- **AI 洞察** — 精选头条 + 潜力黑马 + 趋势信号
- **宝藏项目** — HN/Reddit 热议但 stars 尚少的项目，提前关注窗口
- **水利行业建议** — AI 热点技术方向与水利信息化场景自动匹配

## 快速开始

```bash
# 安装依赖
pip install -r scripts/requirements.txt

# 抓取今日数据
python scripts/fetch.py daily

# 抓取本周数据
python scripts/fetch.py weekly
```

启动本地预览：
```bash
python -m http.server 8080
# 浏览器打开 http://localhost:8080
```

> **⚠️ 无 GITHUB_TOKEN 时**：GitHub API 限 60 次/小时，pipeline 会自动降级——跳过 API 详情补全，仅依赖 GitHub Trending 页面 + HN + Reddit。stars 总数可能缺失，以 stars_added（新增数）为主要指标。建议配置 Token 获取完整数据。

## 配置 GITHUB_TOKEN（推荐）

1. 前往 https://github.com/settings/tokens/new
2. 创建一个 token，无需勾选任何权限（仅用于提升 API 限额）
3. 设置环境变量：`export GITHUB_TOKEN=ghp_xxxx`（或写入 CI Secrets）

## 数据源

| 来源 | 说明 | API 要求 |
|------|------|---------|
| GitHub Trending | HTML 页面解析 | 无需 Key |
| GitHub Search API | 按 AI topics 搜索 | 可选 Token（提升限额） |
| HN Firebase API | 热门帖子提取 GitHub 链接 | 免费 |
| HN Algolia API | 项目名前向搜索（带时间窗口） | 免费 |
| Reddit Hot Posts | AI 子版块热帖提取 GitHub 链接 | 免费 |
| GitHub Issues API | 活跃度补充信号 | 可选 Token |

## 部署

项目设计为部署在 **GitHub Pages**，通过 **GitHub Actions** 每 6 小时自动刷新数据。

1. Fork 本仓库
2. 在 Settings → Secrets 添加 `GITHUB_TOKEN`（可选，用于提升 API 限额）
3. 启用 GitHub Pages（Settings → Pages → Source: `main` branch, `/ (root)`）
4. 手动触发一次 Actions 或等待定时任务执行

## 项目结构

```
├── index.html              # 前端单页面
├── data/                   # JSON 数据文件（由 pipeline 生成）
├── scripts/
│   ├── fetch.py            # 主数据抓取流水线
│   ├── scorer.py           # 四维评分算法
│   ├── insight_generator.py # AI 洞察生成
│   └── water_mapper.py     # 水利领域映射
└── .github/workflows/      # 定时任务配置
```

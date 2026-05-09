# GitHub AI 热点监控

监控 GitHub 上火热 AI 开源项目的网页。通过 **stars 增速** + **Hacker News** + **Reddit** 三个维度交叉验证，发现当下最火的 AI 项目和提前发现"宝藏项目"。

## 功能

- **今日最热 / 一周最热** — 双视图切换
- **AI 洞察** — 精选头条 + 潜力黑马 + 趋势信号
- **宝藏项目** — HN/Reddit 热议但 stars 尚少的项目，提前关注窗口
- **一键更新** — 页面按钮手动触发数据管道，无需等待定时任务
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

## 配置 GH_TOKEN（推荐）

1. 前往 https://github.com/settings/tokens
2. 创建 Classic token，无需勾选权限（仅用于提升 API 限额到 5000 req/hour）
3. 在仓库 Settings → Secrets and variables → Actions → New repository secret 添加：
   - Name: `GH_TOKEN`
   - Value: `ghp_xxxx`
4. 如果需要在页面上使用「更新」按钮手动触发管道，还需要一个带 `workflow` 权限的 PAT，在页面弹窗中输入即可（Token 仅保存在浏览器 localStorage）

## 数据源

| 来源 | 说明 | API 要求 |
|------|------|---------|
| GitHub Trending | HTML 页面解析 | 无需 Key |
| GitHub API | 仓库详情补全（stars、topics、语言） | 可选 Token（提升限额） |
| HN Firebase API | 热门帖子反向提取 GitHub 链接 | 免费 |
| HN Algolia API | 项目名前向搜索（daily 7 天 / weekly 30 天窗口） | 免费 |
| Reddit Search API | 项目名前向搜索讨论热度 | 免费 |
| Reddit Hot Posts | AI 子版块热帖反向提取 GitHub 链接 | 免费 |

管道采用双流架构：**Stream A**（GitHub Trending → AI 分类过滤 → HN/Reddit 交叉验证 → 四维评分排名） + **Stream B**（HN/Reddit → 独立提取 GitHub 引用 → 低 stars 高讨论黑马发现）。

## 部署

项目设计为部署在 **GitHub Pages**，通过 **GitHub Actions** 每 6 小时自动刷新数据。页面上的「更新」按钮可随时手动触发管道。

1. Fork 本仓库
2. 在 Settings → Secrets and variables → Actions 添加 `GH_TOKEN`（可选，用于提升 API 限额；注意 GitHub 禁止自定义 Secret 使用 `GITHUB_` 前缀）
3. 启用 GitHub Pages（Settings → Pages → Source: `master` branch, `/ (root)`）
4. 手动触发一次 Actions 或等待定时任务执行
5. 首次使用页面「更新」按钮时需输入你的 GitHub PAT（需 `workflow` 权限），Token 仅保存在浏览器本地

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

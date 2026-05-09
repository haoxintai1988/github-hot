# CLAUDE.md — GitHub AI 热点监控

## 项目约定
- Python 脚本放 `scripts/`，前端单文件 `index.html`
- 数据文件 `data/*.json` 由 pipeline 自动生成，**不手动编辑**
- Stars 数据必须从页面实际抓取，绝不编造
- 新增数据源需同步更新 `fetch.py` + `scorer.py`（如需加入评分）

## 核心架构
- 纯静态页面 + Python 定时数据管道
- 前端 `index.html` 读取 `data/` 下的 JSON 渲染
- GitHub Actions 每 6 小时运行 `scripts/fetch.py` 更新数据
- 部署到 GitHub Pages

## 评分公式
stars增速(0.40) + HN热度(0.25) + Reddit热度(0.20) + 话题潜力(0.15)
- 话题潜力内含交叉验证加分：HN 和 Reddit 同时有讨论 → +15

## 环境变量
| 变量 | 用途 | 必需 |
|------|------|------|
| GITHUB_TOKEN | GitHub API 认证，提升限额到 5000/hour | **强烈建议** |

**无 Token 限制**：GitHub API 限 60 req/hour，fetch.py 会跳过 API 密集型步骤（详情补全、Issues 活跃度），仅依赖 GitHub Trending 页面 + HN Firebase + Reddit hot posts 提取。stars 总数字段可能缺失，以 stars_added 为主要指标。

## 已知限制
- GitHub Trending 页面只给 stars_added（新增数），不给 stars 总数
- stars 总数需 GitHub API 获取，无 Token 时为可选字段
- HN Algolia 前向搜索带时间窗口：daily 7 天 / weekly 30 天
- Reddit 信号仅来自 hot posts 提取（不再做项目名前向搜索，噪音高且易被限流）
- `reddit_posts` / `reddit_comments` 字段在 merge 阶段丢失，最终 today.json 仅保留 `reddit_ups` 和 `reddit_subreddit`（已知 bug，待修）
- 无 Token 时 pipeline 完成约需 2-3 分钟

## 红线
- 不要硬编码 stars 数据，必须真正抓取
- 不要修改 `data/` 下由 pipeline 生成的文件
- 不要提交 __pycache__ 目录

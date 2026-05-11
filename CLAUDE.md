# CLAUDE.md — GitHub AI 热点监控

## 项目约定
- Python 脚本放 `scripts/`，前端单文件 `index.html`
- 数据文件 `data/*.json` 由 pipeline 自动生成，**不手动编辑**
- Stars 数据必须从页面实际抓取，绝不编造
- 新增数据源需同步更新 `fetch.py` + `scorer.py`（如需加入评分）

## 核心架构
- 纯静态页面 + Python 定时数据管道
- 前端 `index.html` 读取 `data/` 下的 JSON 渲染
- GitHub Actions 每 6 小时自动运行，页面「更新」按钮可手动触发 workflow_dispatch
- 部署到 GitHub Pages
- 双流管道：Stream A（GitHub Trending → AI 过滤 → 交叉验证评分） + Stream B（HN/Reddit → 提取 GitHub 引用 → 黑马发现）

## 评分公式
stars增速(0.40) + HN热度(0.25) + Reddit热度(0.20) + 话题潜力(0.15)
- 话题潜力内含交叉验证加分：HN 和 Reddit 同时有讨论 → +15

## 环境变量
| 变量 | 用途 | 必需 |
|------|------|------|
| GH_TOKEN | GitHub Actions Secret，用于 fetch.py 中 GitHub API 认证（提升限额到 5000/hour） | **强烈建议** |

**注意**：GitHub 禁止自定义 Secret 使用 `GITHUB_` 前缀，因此 Secret 命名为 `GH_TOKEN`，workflow 中通过 `${{ secrets.GH_TOKEN }}` 传入环境变量 `GITHUB_TOKEN`。

**无 Token 限制**：GitHub API 限 60 req/hour，fetch.py 会跳过 API 密集型步骤（详情补全、Issues 活跃度），仅依赖 GitHub Trending 页面 + HN Firebase + Reddit hot posts 提取。stars 总数字段可能缺失，以 stars_added 为主要指标。

## 已知限制
- GitHub Trending 页面只给 stars_added（新增数），不给 stars 总数
- stars 总数需 GitHub API 获取，无 Token 时为可选字段
- HN Algolia 前向搜索带时间窗口：daily 7 天 / weekly 30 天
- Reddit 信号采用三层回退搜索（full_name → repo name → "owner name"）+ Stream B hot posts 反向提取双路径，搜索结果经 URL 去重
- 无 Token 时 pipeline 完成约需 2-3 分钟

## 红线
- 不要硬编码 stars 数据，必须真正抓取
- 不要修改 `data/` 下由 pipeline 生成的文件
- 不要提交 __pycache__ 目录

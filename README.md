# QuestionBank

面向个人与教研团队的题库系统，当前以**刷题**为核心使用路径。支持导入题库、发布后自主练习、错题本，以及组稿、知识点与 AI 辅助等能力。

## 主要功能

### 刷题（核心）

- **自主练习**（`/practice`）：从个人空间或共享空间选择题库后开始。
  - 顺序刷题
  - 乱序刷题（20 / 40 / 60 / 80 / 100 题或全部）
  - 按题型刷题
  - 错题练习
  - 区间刷题（按题号范围）
- 单选、多选、判断题自动判分；填空题、解答题由用户自评。
- 支持“我不知道”，答错或选择不知道会自动记入错题本。
- 可开启“答对后自动下一题”。
- **错题本**（`/practice/wrong-book`）：汇总所有可访问题库中的错题，保留正确答案与解析。

### 题库管理

- 每份导入文档作为一个独立题库（基于导入任务）。
- 个人空间 / 共享空间。
- 题库需发布后才可进入刷题；共享题库发布前需审核。
- 支持在题库详情中查看、修改题目后发布。

### 其他能力

- **智能导入**：Word / Markdown / 图片等，AI 抽取或本地解析后审核入库。
- **组稿工作台**：个人 / 共享空间，试题篮、排版、定稿快照，导出 Word / LaTeX。
- **知识点与标签**：树形知识点、标签分类，支持向量检索匹配。
- **AI 助手**：对话、找题、对稿件提出修改建议等。
- **学科与权限**：多学科、成员角色、审核流程、操作审计。

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.13+、FastAPI、SQLAlchemy Async、Alembic、Pydantic |
| 前端 | Nuxt 4（SPA）、Vue 3、TypeScript、Tailwind CSS 4、Shadcn UI |
| 数据 | 桌面版 SQLite；服务器版 MySQL 8。向量检索使用 ChromaDB |
| AI | 统一 Provider 接口，支持 Gemini 与 OpenAI 兼容接口，配置存数据库 |
| 文档与公式 | Pandoc、Tiptap、KaTeX、MathLive |
| 桌面与部署 | PyInstaller + 系统托盘 + pywebview；Docker Compose |

## 快速开始

### Windows 桌面版（推荐个人使用）

下载 Releases 中的安装包或便携版，启动后以托盘图标运行，首次打开进入初始化向导创建管理员账号即可。

- 安装版数据：`%APPDATA%\QuestionBank`
- 便携版数据：解压目录下的 `data` 文件夹

### 服务器版（Docker Compose）

适用于多人协作。包含 MySQL、ChromaDB、后端、Worker 与前端。

```bash
# 复制并填写环境变量后启动
docker compose up -d
```

详见 `docker-compose.yml`。

### 本地开发

后端（`backend/`）：

```bash
# 依赖管理使用 uv
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

前端（`frontend/`）：

```bash
pnpm install
pnpm dev
```

## 项目结构

```
.
├── backend/          # FastAPI 后端
│   └── app/
│       ├── api/v1/endpoints/   # 路由（含 practice）
│       ├── models/             # 数据模型
│       ├── services/           # 业务服务（导入、导出、AI 等）
│       └── ...
├── frontend/         # Nuxt 4 前端
│   └── app/
│       ├── pages/              # 页面（practice、question-banks 等）
│       └── components/
├── docs/             # 文档站点
└── docker-compose.yml
```

## 开源协议

[AGPL-3.0-or-later](LICENSE)

- 可自由使用、修改、分发，包括商业使用。
- 通过网络提供服务时，必须公开修改后的代码。
- 衍生作品须使用相同协议。

## 贡献

欢迎 Issue 与 Pull Request。开发约定见 `CONTRIBUTING.md`。

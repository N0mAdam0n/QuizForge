# QuestionBank —— AI 原生的题库与组稿系统

**QuestionBank** 是面向教师与教研团队的 AI 原生题库与组稿系统，覆盖 AI 智能导入、多学科题库管理、知识点匹配、审核发布与稿件编排。支持 Windows 桌面版和服务器版，既可个人使用，也可在局域网或团队环境中协作。

![题库示例](./docs/public/examples/questions.png)
![组稿示例](./docs/public/examples/compositions.png)

## 🧰 技术栈

| 层次 | 技术 |
| ------ | ------ |
| 后端 API | Python 3.13+、FastAPI、Pydantic、SQLAlchemy Async、Alembic |
| Web 前端 | Nuxt 4（SPA）、Vue 3、TypeScript、Tailwind CSS 4、Shadcn UI |
| 数据存储 | 桌面版默认使用 SQLite；服务器版使用 MySQL 8。向量检索由 ChromaDB 提供 |
| AI 能力 | 统一 AI Provider 接口，支持 Google Gemini（`google-genai`）与 OpenAI；配置按数据库动态管理 |
| 文档与公式 | Pandoc 文档转换，支持 Word / Markdown 导入；Tiptap、KaTeX 与 MathLive 提供富文本和数学公式编辑 |
| 桌面与部署 | PyInstaller 单文件桌面程序、系统托盘、pywebview；Docker Compose 支持服务器部署 |

## ✨ 核心功能

| 模块 | 说明 |
| ------ | ------ |
| 组稿工作台 | 个人 / 共享空间与文件夹归档、试题篮收集、自由排版与题号 / 分值 / 显示控制、定稿快照版本，导出 Word / LaTeX |
| 我的题库 | 每份导入文档单独成为一个题库；在题库详情内查看、修改与发布，不必进入全局题目管理页面 |
| 自主练习 | 从个人或共享空间选择已发布的完整题库；支持顺序、乱序（20 / 40 / 60 / 80 / 100 题或全部）、题号区间、按题型练习，选择 / 判断自动判分，填空 / 解答题自评 |
| 错题本 | 将所有题库中的错题与“我不知道”的题目统一收录，按用户隔离并保留正确答案与解析 |
| 智能导入 | Word / Markdown / 图片，以及带本地图片的 .zip 或整个文件夹；AI 智能抽取或本地多策略文本解析，审核后按题库发布规则独立保存。详见 [智能导入](https://n0madamon.github.io/question-bank-Nom/features/import) |
| 题目能力 | 知识点 / 标签关联、母子题结构、富文本 + 表格 + LaTeX、公开 / 私有可见性；题目维护按完整题库组织 |
| AI 助手 | 对话中智能找题、创建稿件，并对当前稿件提出增删 / 移动 / 分值等修改；改动先预览，由你应用或放弃 |
| 知识点体系 | 按学科组织的树形知识点，向量化入库，支持 RAG 自动匹配 |
| 学科 & 权限 | 多学科体系、按学科授予只读 / 可编辑 / 学科负责人角色、成员管理。详见 [权限与角色](https://n0madamon.github.io/question-bank-Nom/admin/permissions) |
| 标签管理 | 标签分类管理、Excel 批量导入 |
| 审核工作流 | 草稿 → 待审 → 发布 → 归档，审核日志完整记录 |
| AI 对话 | 多模型聊天（支持图片），可选 Provider / Model，对话历史持久化 |
| 用户 & 登录 | 用户管理、登录统计 |
| 操作审计 | 全局活动日志，支持分页与筛选 |
| 系统设置 | AI Provider / Model 热配置、Prompt Template 管理（超管专属）。详见 [AI 供应商与模型](https://n0madamon.github.io/question-bank-Nom/admin/ai-config) |
| 文件预览 | DOCX / Markdown 源文件在线预览 |

## 🚀 快速体验 (Quick Start)

推荐直接下载**Windows 桌面版**：一个托盘应用，内置后端、前端与 SQLite 数据库，**无需安装数据库或 Docker**。提供安装程序和 ZIP 便携版两种形式。

1. 打开 [GitHub Releases](https://github.com/N0mAdam0n/question-bank-Nom/releases)，下载 `QuestionBank-Setup-x.y.z.exe` 安装，或下载 `QuestionBank-Portable-x.y.z.zip` 解压即用。
2. 启动后应用以**托盘图标**常驻任务栏右下角，右键 → 「打开题库」进入初始化向导（创建管理员账号）即可使用。

安装版数据存放在 `%APPDATA%\QuestionBank`；便携版数据存放在解压目录的 `data` 文件夹。

详见文档：[安装与首次启动及 Lite 便携版](https://n0madamon.github.io/question-bank-Nom/desktop/install) · [个人使用](https://n0madamon.github.io/question-bank-Nom/desktop/personal)

## 🌐 其他部署方式

- **局域网共享** — 桌面版打开共享开关，让同网段的同事一起用，无需额外部署。详见 [局域网共享](https://n0madamon.github.io/question-bank-Nom/desktop/lan-sharing)。
- **服务器版（Docker Compose）** — 多人协作 / 生产环境，完整 MySQL + ChromaDB 技术栈，直接拉取预构建镜像一键启动，无需本地构建。详见 [Docker Compose 部署](https://n0madamon.github.io/question-bank-Nom/server/docker)。

## 🛠️ Windows 本地构建

在已配置 Python、uv、Node.js、pnpm 与 just 的开发机上，从 `backend` 目录运行：

```powershell
just package-to-output
```

该命令构建桌面单文件程序和 Lite 便携 ZIP，并将 `QuestionBank-Desktop.exe` 与 `QuestionBank-Lite.zip` 输出到 `D:\VS Code Compile`。

## 📚 文档与反馈

📖 在线文档：<https://n0madamon.github.io/question-bank-Nom/>

<table>
  <tr>
    <td align="center">
      <img src="./docs/public/qrcode_for_gh_ef2f2e31e4f8_258.jpg" alt="微信公众号二维码" width="180" /><br />
      关注公众号，反馈&获取动态
    </td>
  </tr>
</table>

## 📄 开源协议

本项目采用 [AGPL-3.0-or-later](./LICENSE) 协议。这意味着：

- ✅ 自由使用、修改、分发
- ✅ 商业使用
- ⚠️ **通过网络提供服务时**，必须公开你的修改代码
- ⚠️ 衍生作品必须使用相同的 AGPL 协议

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request。开发环境、项目架构与代码约定请参阅：

- [贡献指南](./CONTRIBUTING.md)
- [开发文档](https://n0madamon.github.io/question-bank-Nom/development/local-setup)
- [架构文档](https://n0madamon.github.io/question-bank-Nom/development/architecture)

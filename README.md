# tomo

项目已初始化，尚未确定产品目标、技术栈或部署方式；当前没有业务程序或运行服务。

## 开始使用

在本目录打开支持项目级 Agent Skills 的编程助手，先读 `AGENTS.md`。
技能位于 `.agents/skills/`，适合在下一次项目会话中发现；当前会话未验证宿主热加载或斜杠命令注册。
若宿主没有发现技能，可明确要求助手读取相应目录下的 `SKILL.md` 并按其流程执行。

可以这样开始：

- “在 tomo 中澄清这个需求，读取 grill-with-docs，沿用已有信息，只追问影响实现的缺失项。”
- “把刚才讨论整理成规格，使用 to-spec，保存到本地任务目录。”
- “使用 to-tickets 拆分任务并标明依赖。”
- “按 implement 实现这个已明确的任务，完成后做 code-review。”
- “使用 diagnosing-bugs 复现和定位这个问题。”

复杂并行开发可使用 `implement-spec`；实际子 Agent 能力取决于宿主工具。

## 项目约定

- 本地任务追踪：[issue-tracker.md](docs/agents/issue-tracker.md)
- 任务状态：[triage-labels.md](docs/agents/triage-labels.md)
- 术语与架构文档：[domain.md](docs/agents/domain.md)
- 技能来源、版本、适配和清单：[skills.md](docs/agents/skills.md)
- 初始化决策：[ADR-0001](docs/adr/0001-project-bootstrap.md)

本次只初始化本地 Git 仓库，不创建远程仓库、不发布、不安装业务框架。

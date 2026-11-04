# 工程技能接入

## 来源与安装

- 上游：https://github.com/mattpocock/skills
- 固定提交：`4ae2317ddb22b046e26455e4f9c9b3aaaf62212d`
- 日期：2026-11-04
- 范围：engineering、productivity，共 27 个技能；不含 in-progress、misc。
- 位置：`.agents/skills/<name>/`。技能文件及随附资源原样安装，逐文件校验 Git blob 与上游提交一致。
- 来源锁定及 SHA256：`docs/vendor/mattpocock-skills.lock.json`。
- MIT 许可证：`docs/vendor/mattpocock-skills-LICENSE`，仅适用于引入的上游内容；未替本项目业务代码选择许可证。

## 使用路径

| 场景 | 技能 |
| --- | --- |
| 选择流程 | ask-matt |
| 澄清需求、沉淀术语和决策 | grill-with-docs、domain-modeling |
| 规格与任务拆分 | to-spec、to-tickets |
| 实现与验证 | implement、tdd |
| 复杂依赖图与并行开发 | implement-spec |
| 故障诊断 | diagnosing-bugs |
| 审查与架构改进 | code-review、improve-codebase-architecture |
| 会话交接 | handoff |

用户显式调用类技能与模型自动调用类技能按各自 frontmatter 区分。
宿主不支持斜杠命令时，直接用自然语言指定读取对应 SKILL.md；是否能调用子 Agent、浏览器等能力以实际工具为准。
下一次项目会话可发现已安装技能；此次未启动新宿主会话验证自动发现。

## 本次配置

使用 setup-matt-pocock-skills 的本地 issue tracker、triage-labels 和 domain 原始模板。
本项目以已授权初始化范围内的可逆默认项完成配置：无远程时本地 Markdown、默认五标签、single-context。
不另外进行模板中的逐项偏好访谈；如要更换约定，直接编辑 docs/agents/。
上游技能保持原文；项目工作约定在 AGENTS.md，优先沿用已知需求，只澄清真正影响实现的信息。
小改动按实际风险验证，无需机械启动整套流程。

## 升级

先检查上游差异、技能引用与脚本，再显式替换项目内文件，更新锁定清单并验证；不自动跟随 main。
避免同一项目再通过全局插件重复安装相同技能。

## 安装清单

- `ask-matt`
- `code-review`
- `codebase-design`
- `diagnosing-bugs`
- `domain-modeling`
- `grill-me`
- `grill-with-docs`
- `grilling`
- `handoff`
- `implement`
- `implement-spec`
- `improve-codebase-architecture`
- `pr`
- `prototype`
- `research`
- `retro`
- `setup-matt-pocock-skills`
- `tdd`
- `teach`
- `to-questionnaire`
- `to-spec`
- `to-tickets`
- `triage`
- `wait-what`
- `wayfinder`
- `wizard`
- `writing-for-agents`

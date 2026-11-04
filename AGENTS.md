# tomo

项目状态与入口见 `README.md`。业务目标和技术栈尚未确定，实施业务功能前先明确验收条件。

## Working agreement

- 沿用已明确的需求，自主完成可逆的本地工作；仅对影响实现的缺失信息提问。
- 调用技能前读取对应 `SKILL.md`，按需加载其引用文件，不一次性加载全部技能正文。
- 本地宿主支持的工具才是实际能力来源；技能文件不授予工具、凭据或执行权限。
- 排错先建立可复现的故障信号；验证针对用户可见行为。按改动风险选择必要检查。
- 任务完成时说明改动、实际验证及未验证项；业务功能未实现时不宣称可运行。

## Agent skills

### Issue tracker

使用本地 Markdown：`.scratch/<feature>/spec.md` 和 `.scratch/<feature>/issues/`。操作见 `docs/agents/issue-tracker.md`。

### Triage labels

使用上游默认五种分诊状态。映射见 `docs/agents/triage-labels.md`。

### Domain docs

采用 single-context：根目录 `GLOSSARY.md` 与 `docs/adr/`。探索、规格和设计工作前按 `docs/agents/domain.md` 读取相关内容。

### Skill selection

工程流程与调用入口见 `docs/agents/skills.md`；不明确用哪一个时读取 `.agents/skills/ask-matt/SKILL.md`。

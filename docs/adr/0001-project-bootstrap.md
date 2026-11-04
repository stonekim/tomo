# ADR-0001：项目级工程技能与本地任务追踪

- 日期：2026-11-04（Asia/Shanghai）
- 状态：Accepted

## 背景

用户要求在 lab 目录初始化 tomo，并使用 mattpocock/skills 的内容。
当前没有远程仓库，也没有业务需求或技术栈约束。

## 决策

1. 项目位置为 `/home/pi/codex/lab/tomo`，Git 默认分支 `main`。
2. 将上游 engineering 和 productivity 两组的 27 个技能原样安装到 `.agents/skills/`；排除 in-progress 和 misc。
3. 固定源提交，保留许可证和文件校验清单；更新需显式进行。
4. 依据上游 setup 模板使用本地 Markdown、默认分诊标签和 single-context 文档布局。
5. 这些都是本次初始化的可逆本地默认项，不新增逐项确认；用户可编辑 `docs/agents/` 更换约定。
6. 暂不创建业务代码、选技术栈、配置远程或部署服务。

## 后果

技能只影响本项目。项目级 Skill 发现取决于宿主，新会话中需核对；不能仅凭文件安装推断工具或命令已注册。

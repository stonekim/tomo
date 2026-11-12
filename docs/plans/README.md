# Check a plan · 现实计划与复盘（TOMO-MVP-02）

## 已实现的产品动作

- 新建 **7–30个日历日**的现实计划：目标、完成标准、明确截止时刻、IANA时区、已确认事实、未知项、估计剩余工时、每周可用工时和用户原判断。
- 创建存档与首次事前判断在同一个SQLite事务内完成；创建键按用户隔离，重试不会再建计划。
- 时间预算基线只算「截止前可用小时 vs 自报所需小时」，**不是现实成功率**。工时缺失则为 `unknown/null`，不填0、不编造精确百分比。
- 每周手动更新会追加 `update`；改目标/完成标准/截止/时区必须追加 `judgment`。历史判断和当时预算保持不变。
- 到期才可回填 `outcome`，指定具体事前判断。服务器从数据库回读该判断的原截止和标准，而不是套用最新标准。记录是用户自报，不冒充外部验收。
- 结果未知或尚未填写时，对照结果保持 `null`。对照展示用户原判断、简单时间预算基线和自报结果；不据单个计划宣称预测准确率。
- 修正回填会追加新版本，且须写明更正原因，不能覆盖旧结果；交错对多个判断回填也不能绕过原因要求。
- 条件建议仅点击时调用固定的服务器模型服务。模型输出需通过严格JSON形状、恰好两情景和禁止数值概率表述的检查；不会自动写入事实/判断/结果。未配置、失败或格式不合格时标明规则建议。Mock永远标明mock，不冒充真实调用。

## 组合后端

```python
from tomo.platform.api import create_app
from tomo.platform.config import Settings
from tomo.platform.rules import RuleRegistry
from tomo.plans import create_router, validate_plan

rules = RuleRegistry()
rules.register('plan', validate_plan)
app = create_app(Settings.from_env(), rule_registry=rules,
                 domain_routers=[create_router()])
```

与游戏组合时，在同一个registry中注册game规则，并同时传入游戏router。不要再次调用独立app再共享全局状态。

仅需计划域的开发入口：

```sh
TOMO_DATABASE=./data/tomo.sqlite3 python -m uvicorn tomo.plans.api:create_plan_app \
  --factory --host 127.0.0.1 --port 8000
```

`create_plan_app(settings, clock=...)` 的clock注入供测试使用；线上默认UTC服务器时间，不开放客户端时钟切换接口。

### 平台可信上下文补丁（须一同集成）

`Store.create_save` 的初始化规则事件带服务器 `_now`。`append_version` 带服务器 `_now`；结果版本额外带数据库解析的 `_judgment={id,content,created_at}` 与 `_outcome_count`。客户端同名参数仍被冻结的 `VersionProposal.additionalProperties=false` 拒绝。域规则缺少可信上下文会拒绝结果。不要为了兼容客户端而透传这些保留字段。

创建计划的事务集中在 `PlanService.create`，复用platform的事务、ID、幂等与序列化方法，并只写现有saves/plan_versions/idempotency三表，不创建迁移或平行存储。这样存档、首个判断及幂等回执一起提交或回滚。

## 接口（全部继承Bearer用户鉴权）

|方法|路径|作用|
|---|---|---|
|GET|`/api/v1/plans`|本人计划详情列表，包含当前卡片与历史|
|POST|`/api/v1/plans`|原子创建计划和首次判断|
|GET|`/api/v1/plans/{id}`|当前卡片、全部版本、到期状态和复盘对照|
|POST|`/api/v1/plans/{id}/versions`|追加update或judgment|
|POST|`/api/v1/plans/{id}/outcomes`|按特定判断追加到期结果或更正|
|POST|`/api/v1/plans/{id}/suggestions`|条件建议，不修改存档|
|GET|`/api/v1/plans/{id}/review`|事前判断与结果的逐版本对照|

窄类型请求已进入OpenAPI。独立机器契约：`contract-v1.json`，或调用 `tomo.plans.contracts.contract_document()`。`openapi-v1.json` 是只包含平台+计划域的参考快照，不覆盖完整产品的共享OpenAPI文件。

### 请求形状

- create：`{title,idempotency_key,card}`
- card：`{goal,completion_criteria,due_at,timezone,facts,unknowns,required_hours,available_hours_per_week,user_judgment}`。工时可null，事实/未知各最多20条，每条最多2000字；用户判断为 `yes|uncertain|no|unknown`。
- version：`{expected_revision,idempotency_key,kind,card,update_note,recorded_at}`，kind为 `update|judgment`。
- outcome：`{expected_revision,idempotency_key,based_on,status,evidence,actual_hours,recorded_at,correction_note}`，status为 `completed|not_completed|unknown`。
- 建议响应：`{mode,model_status,suggestions:{risks,scenarios:[{name,assumptions,actions},...]},notice}`。

`recorded_at` 是用户操作时生成一次的RFC3339带偏移时间；服务端要求首次提交时与服务器时钟相差不超过5分钟，并以服务器DB记录时间作为审计时间。**网络重试必须复用完全相同的body与key**，不能重算recorded_at。复播已提交请求先命中幂等记录，不因后来到期而重复写入。UI已保留未确认请求用于显式重试；用户编辑输入后才生成新请求。

日期窗口按所选IANA时区的日历日期计算，避免夏令时把7日误判为167小时不足7日；到期检查使用带偏移的精确UTC时刻，不提前一天或提前一秒。每周可用工时按真实剩余秒数折算，不把时区日历差当物理工时。

## 前端交接

`web/src/plans/index.js` 导出同步 `mountPlans(root, context)` 并返回cleanup。

```js
const cleanup = mountPlans(container, {
  api: async (fullPath, {method='GET', body}={}) => { /* 带当前用户鉴权，返回解析JSON */ },
  saveId: selectedSaveId,
  onUnauthorized: () => { /* 回登录页 */ },
  onSaveCreated: save => { /* 保存选中存档路由 */ },
  refreshSaves: () => { /* 刷新公共存档列表 */ },
  navigate: (domain, saveId) => { /* domain === 'plan' */ }
});
```

API传入**完整 `/api/v1/...` 路径**；错误对象需带 `.status`、`.code`。CSS通过相对import.meta.url载入同目录style.css，静态服务器须一起映射。DOM使用textContent/value展示用户/模型文本，不执行HTML。保存中锁定本模块控件，避免重入或失去未保存编辑；网络失败不自动重放写操作。

## 测试与验证边界

```sh
PYTHONPATH=src python -m pytest tests/platform tests/plans -q
PYTHONPATH=src python tests/plans/browser_harness.py
```

Browser harness只在临时数据库和127.0.0.1临时端口运行，测试结束停止服务器，使用合成资料和禁用模型；Playwright/Chromium二进制位置可通过`TOMO_PLAYWRIGHT_MODULE` / `TOMO_CHROMIUM_PATH`环境变量覆盖。真实模型、真实用户研究、未来结果准确性、整站账户壳及生产部署不在本模块已验证范围，留04集成验收。公开启用真实模型前还需要部署层的速率/并发/用量预算与provider输出上限，不应仅依赖按钮禁用。

确切测试计数和命令回执见verification.json。没有用户真实计划、访问token、数据库或凭据进入提交。

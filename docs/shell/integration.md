# 03 公共产品壳与集成约定

## 文件与启动

`web/index.html` 加载 `web/src/shell/index.js` 和自身CSS；无第三方JS/CDN或前端构建步骤。部署服务必须将 `/api/v1/*` 路由给平台/领域服务，其余静态路径映射 `web/`。若部署在子路径，可通过HTML的`meta[name=tomo-api-base]`集中配置同源API前缀（不设置时由HTTP模块地址自动推导；根路径为`/api/v1`，子路径如`/read/tomo/app/api/v1`）；客户端拒绝跨源前缀，不能把密钥放入此项。不要将带secret的环境文件放进web目录。04负责正式ASGI组合、HTTPS、持久数据库与部署，不要使用纯静态HTTP服务冒充产品可用。

03只覆盖公共体验：注册/登录、两种产品入口、按domain存档、刷新恢复、退出/清除本机凭证、失败重试与隐私边界。01/02分别实现领域UI与规则。

## 领域模块协议

- `web/src/game/index.js` 导出 `mountGame(root, context)`。
- `web/src/plans/index.js` 导出 `mountPlans(root, context)`。
- 函数可为async，返回清理函数或undefined。所有UI放入root，不操作壳DOM或全局sessionStorage；在cleanup撤销订阅/事件监听与未完成请求。路径切换后的旧root会被移出DOM。
- `context.api(path, {method, body, signal})`：path为相对于`/api/v1`的站内绝对路径，例如`/game/saves`。缺method时有body即POST，否则GET。自动附加bearer，发送JSON并返回解析后的JSON；204返回null。错误抛出带`status`和`code`的`ApiError`。401自动清除会话并返回登录区，避免领域继续显示另一账号缓存。
- `context.saveId`、`context.save`：当前所选存档，开始新体验时均null。`save`来自实际`GET /saves/{id}`，类型和拥有者检查在服务端执行。
- `context.navigate(domain, saveId)`：domain为game或plan，使用`#/game/<id>`或`#/plan/<id>`选择存档。URL不含token/密码。
- `context.onSaveCreated(save)`：创建后调用，传Save或其id；壳刷新列表并导航至新存档。
- `context.refreshSaves()`刷新列表；`context.onUnauthorized()`使当前登录失效。
- `context.session.userId`只为展示/本地隔离辅助，不得作为后端owner参数。

领域模块缺失或动态加载失败显示“体验暂未接入”，不会生成假存档或假成功。此边界不能作为完整游戏/计划交付。模块域CSS必须自己import，并在各自选择器内限定；公共`domain.css`只给基础表单与表格响应式样式。

## 数据控制

仅会话bearer/user_id/expiry存入sessionStorage，不保存密码、提示词或业务正文；刷新同一标签页可恢复。退出调用服务器`POST /auth/logout`后本地清除；网络失败仍清除本机凭证，但明确服务器撤销结果未确认。

00没有远端删除/导出接口。页面明确不支持永久删除，不提供假删除按钮，也不将退出当作删除。需04/平台协调后续添加有权限检查、二次确认与可验证结果的删除接口；此版本保留明确边界。

## 验证

```sh
node --test tests/shell/api.test.cjs
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python tests/shell/run_browser.py
```

浏览器检查使用本机Chromium、临时SQLite、真实平台HTTP API、合成账号/存档；只在QA临时app注册允许合成初态的validator，不证明游戏/计划业务规则。测试故意使两个领域模块503以验证恢复信息，即使在集成仓库也不依赖它们。真实注册、登录、存档列表、刷新、双域筛选、网络错误、会话撤销、393/1440px、键盘与无JS异常均检查；04必须另验完整领域路径和真实模型。

证据保存在`.scratch/_tmp/shell-qa/`（不公开、不入Git）。测试finally关闭自己的浏览器/服务器；不操作全局浏览器或线上数据库。

## 本线验收结果

5项Node API/凭证边界检查通过；18项真实Chromium检查通过（包含恶意存档标题只作纯文字，不注入HTML）。首轮仅QA夹具误把Save响应字段用作SaveCreate，导致422；已按冻结契约改为`state`并保留首轮失败。最终手机/桌面截图已查看，未横向溢出。回执摘要和证据哈希见`verification.json`；实际临时记录在上述QA目录。没有修改平台/契约、支付或生产服务。

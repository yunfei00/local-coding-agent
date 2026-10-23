# M4 全面修复与使用约定

## 统一目录

Provider Connections / Model Profiles 是 Chat 和 Task 的共同目录。旧 Provider 页只导航到 Models & Routing；旧配置和受保护密钥保留兼容。旧接口发现的模型增量导入 legacy 连接；用户改过 legacy 连接地址时，不用旧服务返回值污染它。

普通 Chat 使用 `profile:<model_profile_id>`，请求通过原 ModelCatalog.resolve 创建 Provider，实际 Base URL、Key 引用、Model ID、输出限制及视觉声明均来自该 Profile。完全移除“同名模型可能是 Executor”的猜测。重名跨连接依靠 Profile/Connection 区分。Chat 下拉框按连接分组、支持搜索。加载失败不自动挑另一个收费模型。

Settings 可保存 Default Chat Model；新 Thread 使用此默认值，现有 Thread 保留选择。旧裸模型名在能唯一确定已迁移连接时增量绑定；跨连接歧义或配置被删除时保留原记录，明确不可用，需重新选择。旧数据从未记录的 Provider 历史不能凭字符串恢复，不猜测。迁移可以重复执行，不重置 SQLite。

## 三种模型身份

- Chat：每 Thread 独立选择；当前请求身份实时显示，执行记录保留实际 Profile/连接/Model ID。
- Task Executor：只由任务冻结配置决定；普通 Chat 切换不会改变它。旧任务需要明确 Apply configuration 更新。
- Vision Observer：Chat 可在 Settings 独立选择；Task 可以单独选择，无需创建 GUI 合约；兼容旧 GUI 合约的 vision_profile_id。显式选择优先使用观察模型，否则由支持图片的编码模型直接观察，或使用 UIA。Local-only 禁止在线观察。

Observer 只返回不可信观察文字，不接收工具权限。Task 的观察调用复用 RoutedProvider 和 BudgetGuard，普通 Chat 的观察调用纳入原 ExecutionBudget、请求超时和取消。所有桌面访问与图片上传仍经过原审批。

截图经实际 JPEG 多模态消息发送；路径或 OCR 文字不算图片。单次捕获消费一次，同 owner 已消费的相同截图不反复上传。诊断区别排队附件和实际 HTTP；不含原始 Base64。能力声明与最近 Test Vision 结果分别显示，不把声明当作测试通过。

## Windows 截图

保留 PrintWindow 客户区/DPI 归一、仅前台无覆盖回退、PID/代次检查、锁屏/UAC/跨会话保护。增加 capture_method / raw_capture_valid，保留尺寸、DPI、遮盖比例。

Edit、可编辑 Document、Notepad RichEdit 继续遮盖；只读 Chromium 页面根 Document 不整页遮盖。黑屏检测在遮盖之前，暗色主题不因为编辑区遮盖而误报失败。Electron 开启原生 accessibility 以暴露语义控件，不关闭安全机制。

## 复现与验证

```powershell
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
uv run python -m unittest discover -s tests -p test_unified_chat_profiles.py -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
uv run python scripts/validation/credential_scan.py
git diff --check
```

必须区分生成图片的 HTTP 协议测试、真实 WinForms 截图通过 HTTP 传输的测试，以及在线模型推理。用户历史百炼 qwen3.8-flash 五项 PASS / executor_bound=true 是用户历史证据，本轮没有付费 Live Test 授权，真实在线 API 为 NOT RUN。未请求或读取用户 Key。

全部 GUI 用例只操作临时工程或明确授权窗口；截图留本机，不提交。软件不自行推送用户工程、不自动接受代码 Diff、不发布安装包。

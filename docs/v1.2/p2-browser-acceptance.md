# v1.2 P2 — 浏览器自动化操作与验收

## 能力
- `browser_snapshot`：公开网页只读快照
- `browser_session`：`diagnose`、`open`、`snapshot`、`navigate`、`back`、`forward`、`click`、`fill`、`select`、`check`、`uncheck`、`press`、`scroll`、`wait`、`tables`、`screenshot`、`workflow`、`close`
- 设置 → 浏览器自动化：中文网址栏、会话管理、DOM 元素列表、CSS 选择器操作、网页文本、表格提取、工作区 PNG 截图、JSON 自动化步骤、历史记录、依赖诊断
- `workflow` 最多 20 步，遇到首个错误即停止并返回失败步骤
- 会话按项目工作区隔离，单项目最多三个并行会话；关闭会话会释放 Chromium
- 浏览器只允许访问解析为公网 IP 的 HTTP(S) 网站，限制同一主机；禁止下载和 service workers；截图仅能保存到当前工作区的新 PNG 文件
- 点击、按键、勾选、下拉、自动化工作流的 UI 操作必须确认；所有 Agent 工具仍经过既有权限机制

## 安装
项目 Python 环境需安装 Playwright Python 包并下载 Chromium 浏览器。Windows 使用项目 uv 环境执行：

```powershell
uv pip install --python .venv\\Scripts\\python.exe playwright
uv run python -m playwright install chromium
```

依赖安装需联网；运行时不需要 Playwright 云服务。安装后打开「设置 → 浏览器自动化 → 检查 Playwright / Chromium 环境」。

## 验收用例
1. 环境诊断：未安装时给出明确缺失提示；安装后两个检测项为 true
2. 公开 HTTPS 页面打开、快照、DOM 元素列表、标题和文本
3. CSS 唯一匹配后输入/点击/下拉/滚动；匹配零个或多个元素时拒绝执行
4. 前进、后退、同域导航；跨域跳转被拒绝
5. 导出 PNG 截图到工作区；已有文件、越界路径拒绝覆盖
6. 提取 HTML 表格；20 步以内工作流顺序执行，失败即停止
7. 关闭会话后无法继续操作；三个会话上限
8. `localhost`、`127.0.0.1`、内网 IP、`file://`、带凭据 URL 被拒绝
9. 切换项目时旧项目会话 ID 不可在新项目使用
10. Electron 前端 TypeScript 检查、前端测试和 Windows 打包验证

## 安全限制
网页文本、链接、表单内容都是非可信输入，不允许当作 Agent 指令执行。静态 DNS 校验与请求拦截并不能构成完全的网络沙箱；在高安全网络应叠加系统级防火墙或独立网络隔离。表单提交可能产生真实外部效果，应在用户授权后操作。

## 完成判定
以上代码已接入 P2 分支。只有 GitHub CI、Playwright/Chromium Windows 真机 E2E、前端打包和实际网页交互全部通过，才能宣称 P2 已验证完成；本文件不等于测试通过证明。

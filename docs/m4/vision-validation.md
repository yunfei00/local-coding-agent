# 视觉能力与截图验证

`supports_vision` 只表示用户显式声明。诊断不按模型名称推断，也不会在未经测试时给模型加“视觉已通过”状态。

诊断程序在内存通过 Pillow 绘制 640×360 JPEG：标题 `LCA Vision Test`、蓝色 Settings 按钮、一个输入框及随机 `CHECK-xxxxxx`。随机校验文字只在图像像素中，不出现在请求文字。要求 JSON 精确匹配标题、按钮颜色/文字、输入框数量和校验文字；不支持图像、无效 JSON、缺字段或读错任一值都失败。每轮最多发送一张合成图，绝不使用用户桌面截图连接诊断。

`OpenAICompatibleProvider` 原生 `image_url` 数组发送真实 base64 JPEG；没有把截图 OCR 成文本后假装视觉识别。测试用真实 aiohttp 服务验证 HTTP 请求中的 JPEG 字节、模型 ID、Token 限额和 function schema；模型响应可替换。桌面 smoke 故意返回 HTTP200 和错误 CHECK，确认 UI 显示视觉 FAIL。

自主 GUI 验收默认 UIA。显式指定 `vision_profile_id` 后，先通过 M3 桌面窗口范围检查及图像上传审批，遮盖 Edit/敏感控件，再发送授权 JPEG 给观察器。该 profile 可与编码 Executor 相同。观察器只返回 `{"observations":[字符串],"errors":[字符串]}`；错误、非 JSON、额外字段或工具调用均失败。观察结果是补充证据，不能替代冻结的真实控件断言，不能绕过审批发点击。

截图默认只在本地任务产物目录保存，含 SHA256/时间/窗口 generation。授权上传时说明第三方在线服务可能接收图片；拒绝上传后任务暂停，观察模型调用数为零。UI 文字是不可信数据，不能当作系统/工具指令。模型不支持图片时使用 UIA；应用缺少可访问控件或 PrintWindow 不可用时明确失败，不凭空报告正确。

M3 屏幕模式仍仅组合授权窗口，其他像素黑色；不访问其他用户、锁屏、UAC、提权窗口。输入框内容遮盖，普通输入通过 UIA ValuePattern 回读及独立状态断言核对。自绘内容、敏感控件识别的启发式限制、异构多屏覆盖及未打包验证边界继续适用。

本次百炼真实文本、图像、Function Calling 均 NOT RUN，原因是本机该连接无凭据引用、无独立受保护 key 文件，环境无 key；未得到另行启用 Live Test 的授权。不能把文档或模型名称当作实测结果。

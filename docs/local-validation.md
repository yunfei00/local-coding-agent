# 编号式本地自动验收

在仓库根目录运行：

```powershell
uv sync --locked
npm.cmd --prefix desktop ci
uv run python scripts\validation\check.py
```

脚本依次执行 Python unittest、桌面 TypeScript typecheck、桌面单元测试和构建。优先使用 uv 锁定环境，即使由系统 Python 启动，也会选择项目环境；Windows 自动解析 npm.cmd。屏幕显示各阶段 PASS/FAIL 和 `ERR-001` 编号及简要错误。完整 stdout/stderr 存在 `validation-reports/<运行ID>.log`，阶段命令、耗时、退出码与结构化错误存为同名 JSON。运行 ID 使用北京时间。不同运行的编号不保证一致，反馈时请附运行 ID 和编号。报告只保存本地，已加入 Git 忽略，不自动上传日志。

注意：错误摘要为启发式提取，遇到未识别的失败会给出退出码和日志路径；如果多个测试共享同一导入问题，可能产生重复的摘要。

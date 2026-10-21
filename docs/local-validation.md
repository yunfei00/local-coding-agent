# 编号式本地自动验收

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\validation\check.py
```

脚本依次执行 Python unittest、桌面 TypeScript typecheck、桌面单元测试和构建。屏幕仅显示各阶段 PASS/FAIL 和 `ERR-001` 等编号及简要错误。完整 stdout/stderr 存在 `validation-reports/<运行ID>.log`，结构化错误列表存为同名 JSON。不同运行的编号不保证一致，因此反馈时请附运行 ID 和编号。该脚本不安装依赖，也不覆盖工作区文件；运行前应先完成 `uv pip install -e .` 和 `npm ci`。

注意：错误摘要为启发式提取，遇到未识别的失败会给出退出码和日志路径；如果多个测试共享同一导入问题，可能产生重复的摘要。

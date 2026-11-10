# Excel 技能

用于读取、分析和创建 XLSX。优先使用后台 openpyxl，必要时请求授权使用 Windows Excel COM。不要执行工作簿宏；保留原始文件，输出新路径。通过 `python -m agent.skills.cli` 的 inspect/create/verify 命令操作。公式写入不代表已经计算，必要时用 Excel COM 重新计算并核验。
# 发布门槛（2026-11-06 最终决策）

- [x] FULL_ACCESS后端统一决策及代码四角色、GUI、撤销真实分项。
- [x] 方案A本地HTTP真实下载/文件/SHA测试及实际安装版UI补测。
- [x] Setup/Portable实际运行，前后端、聊天、文件写入、重启；无SDK PATH/无Git。
- [x] schema6→7实际覆盖升级及卸载数据保护（历史有效证据）。
- [x] 产品63d9e16完整打包/本机实装/Windows与Ubuntu核心CI，候选42226827888全部通过。
- [ ] 最终文档与归档路径提交的PR必需CI（提交后自动执行，不绕过）。
- [ ] PR #33 Ready并按规则合并，main CI通过。
- [ ] main正式源码构建，创建v1.0.0，上传并下载复核Setup/Portable/SHA。

不再要求干净系统、自动安装重启、重复四角色+GUI同任务组合。它们的NOT RUN/历史FAIL保留为覆盖限制，不改写为PASS。未满足当前必需门槛时不发布；发布事实以Release和CI记录为准。

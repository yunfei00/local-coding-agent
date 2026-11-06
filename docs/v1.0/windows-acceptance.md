# Windows 安装验收（进行中）

必须使用真正构建的安装包。开发启动、Mock Provider、PATH隔离均按实际范围标注，不冒充干净Windows镜像。

待实际记录：全新安装/首启、无SDK、无Git创建工程、模型配置与聊天、文件修改/真实测试、GUI、多角色、FULL_ACCESS无重复普通审批、撤销、重启数据、升级/卸载、故障恢复、SHA256。

当前本机未发现可用Hyper-V管理、WindowsSandbox、VirtualBox或VMware/QEMU入口；注册表未发现现有Local Coding Agent安装。将先构建候选，继续验证隔离目录及CI临时Windows。无法取得必需干净环境证据时记录BLOCKED，保留PR，不创建正式Release。

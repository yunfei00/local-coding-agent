# Git 与自动交付

复用现有 Git 状态、Diff、Worktree、stage/unstage、commit_prepare、commit 与审批工具。角色约束不能绕过原权限。用户既有文件和未提交修改不得被 reset、clean 或强制覆盖。

`git_ci_status` 只读取当前 GitHub origin、指定完整 SHA 的实际 workflow runs，使用已授权 gh CLI 的固定 argv，最多 10 条、30 秒，取消时清理子进程。非 GitHub origin、无 Git、无 gh、授权或网络问题均明确失败，不能把没有记录解释为 CI 通过。它没有触发 CI、推送或合并能力。

工作流完成后，程序在应用数据目录 `workflow-deliveries` 原子生成脱敏 JSON 与中文 Markdown。内容包括目标、修改文件、步骤工具证据、真实测试、独立审查、调用事件、Git Diff 摘要、未完成事项及 PR 草稿。正文不会放到被测工程，避免污染业务测试。

PR 草稿仅准备标题/描述；真正 Push、创建远程 PR、合并及发布仍需要用户明确授权和原有审批。该功能不凭模型文字伪造测试通过。

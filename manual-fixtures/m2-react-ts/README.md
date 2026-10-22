# M2 React + TypeScript 故障工程

独立运行：`npm ci`，然后 `npm run typecheck`、`npm test`、`npm run build`。初始 App.tsx 有真实 TS2322 类型错误；修正类型后 math.ts 的减法会让真实 node:test 断言失败。测试应保持不变。

修复后 `npm run dev` 启动真实 Vite 服务（本地随机端口），`npm run probe` 通过 HTTP 验证首页与 React 转换模块。服务 PID/地址写入被忽略的 runtime/server.json；由 Agent 的 start_process/read_process/stop_process 管理生命周期。

自动化复制本工程到临时 Git 仓库和受管理 Worktree，真实 npm ci 安装锁定依赖，不要求修改本目录或手工验收。不生成安装程序。

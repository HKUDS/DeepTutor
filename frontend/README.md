# Lumen 前端

SeedCode Trae 工作台壳。`deeptutor start` 默认构建并托管本目录。

```bash
npm ci
npm run dev
```

独立调试页：http://127.0.0.1:5174（把 `/api` 反代到后端 `:8001`）。

通过 `deeptutor start --dev` 启动时，端口以 `system.json` 的 `frontend_port` 为准（默认 `3782`）。

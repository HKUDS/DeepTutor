# DeepTutor 前端

SeedCode Trae 工作台壳（从 Askora `apps/frontend` 拷入）。P0 接 DeepTutor `/api/v1/ws` 与 sessions REST。

旧 Next.js 前端仍在仓库的 `web/`，`deeptutor start` 默认仍起它。

```bash
npm ci
npm run dev
```

页面：http://127.0.0.1:5174（把 `/api` 反代到后端 `:8001`）

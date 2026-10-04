# test: VisualizationViewer 渲染分支补测 — 证据（2026-10-03）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12）
分支：`test/visualization-viewer-20261004`
新增测试：`web/tests/visualize/VisualizationViewer.spec.tsx`（22 个用例，vitest + testing-library/jsdom）

## 命令

```bash
cd web
npm ci
npm install --no-save @vitest/coverage-v8@4.1.11   # 仓库未内置 coverage provider，仅装进 node_modules
# 基线（新分支上先不跑新测试）
npx vitest run --coverage --coverage.include='components/visualize/**' --coverage.reporter=text
# 加入新测试后（同命令）
npx vitest run --coverage --coverage.include='components/visualize/**' --coverage.reporter=text
```

注：仓库 vitest include 规则为 `tests/**/*.spec.ts(x)`，故文件名用 `.spec.tsx`（任务卡中写的
`.test.tsx` 不会被 vitest 收集，且 `.test.ts` 归 `test:node` 管线，不适用 jsdom 组件测试）。

## 覆盖率前后（web/components/visualize/VisualizationViewer.tsx）

| 指标 | 前 | 后 |
|---|---:|---:|
| Statements | 1.69% (4/299) | **74.57% (176/299)** |
| Branches | 0% (0/230) | **50.86% (117/230)** |
| Functions | 0% (0/84) | **71.69% (38/84)** |
| Lines | 1.49% (4/268) | **61.56% (165/268)** |

与 audit/coverage-gaps-20261003 报告一致：改前 232 条语句缺失 / 1.7%。

## 测试结果

- 基线全套件：113 files / 471 tests 全通过（新分支 origin/main 本身绿）
- 加新测试后全套件：**114 files / 493 tests 全通过**（+22）
- `npm run typecheck` 通过；`npx eslint tests/visualize/VisualizationViewer.spec.tsx` 通过

## 用例覆盖的三态与分支

1. 合法 mermaid：loading 占位（"Rendering diagram..."）→ 渲染成功注入 svg，`mermaid.render` 收到正确内容
2. 非法语法错误态：`mermaid.render` reject → "Diagram rendering error" 卡片 + 错误信息 + 源码可查
3. 空内容态：不触发 `mermaid.render`、无 loading、无错误卡片（不白屏）
4. 其余渲染分支：svg 清洗（去 script）与非法 svg 错误卡、多 svg 拆分、chartjs 解析成功/围栏剥离/解析失败错误卡/卸载 destroy、html iframe + "Open in new tab" + 高度桥接消息、插件 iframe（有/无 entry_url）、geogebra、未知 renderer 错误、manim 委托、Show code / Copy code / 全屏 portal + Escape 关闭、review 备注

## 已知环境限制

- jsdom 对 `image/svg+xml` 文档不支持 `[id]` 属性选择器，`sanitizeSvg` 的 id 重排分支在该环境下不可观测，
  测试只断言 script 剥离（安全相关行为），未断言 id 前缀。

## 未覆盖（残余）

剩余未覆盖语句集中在：全屏 portal 内层交互的部分分支、Geogebra/MathAnimator 真实子组件内部（已 mock）、
少量 chartjs/iframe 边界分支（详见 coverage-after.txt 的 Uncovered Line #s）。

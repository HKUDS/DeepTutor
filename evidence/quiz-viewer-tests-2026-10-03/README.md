# QuizViewer 冒烟与判分交互补测（AGEN-285 / 覆盖备选 16）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12）。
分支：`myfork/test/quiz-viewer-smoke-20261003`（独立 worktree，未触碰主工作区）。

## 产物

- `web/tests/quiz/QuizViewer.smoke.spec.tsx` — 11 个用例，全部通过。
- 无任何产品代码改动（`git status` 仅新增上述测试文件与本证据目录）。

### 命名说明

任务卡写的 `QuizViewer.smoke.test.tsx` 在本仓库不可运行：`web/vitest.config.mts`
的 include 只有 `tests/**/*.spec.ts|tsx`（`.test.ts` 走 node 测试线，无 jsdom/React）。
因此按仓库既有组件测试惯例命名为 `QuizViewer.smoke.spec.tsx`，目录 `tests/quiz/`
与任务卡一致。

## 覆盖点 ↔ 验收映射

| 验收 | 用例 |
| --- | --- |
| 渲染冒烟 | 空列表渲染 null；卡片渲染题干/三个选项/进度 0/2；首题 Previous 与 Check Answer 禁用 |
| 选项作答→提交→判分反馈 | 选对→"Correct"+解析区；选错→"Incorrect"，正确项绿框、错选项红框；选项提交后锁定；T/F(concept) 走 `resolveConceptAnswer` 判定 |
| 重做路径 | Retry 清空选中与反馈 → 可重新作答并重新判分（对→错重判） |
| 进度与导航 | 提交后计数 1/2；已完成且判对的题号 chip 变绿；Next/Previous/chip 均可切题 |
| mock API：notebook | 提交即 `upsertNotebookEntry`（session_id/turn_id/question_id/user_answer/is_correct）；挂载时按 (session, q_x, turn) 逐题 `lookupNotebookEntry`（#487/#677 turn 作用域） |
| mock API：成绩上报 | 全部作答后 `recordQuizResults` 恰好调用 1 次，payload 含逐题 question_id/user_answer/is_correct |
| mock API：无 turnId 本地态 | 不发生 lookup/upsert/record 任何调用（本地判分，无跨 quiz 状态泄漏） |
| AI 判分流（mock WS） | `startQuizJudge` payload 含题干/题型/答案/language；onDone 后判词渲染、Judging... 消失、参考答案区切走 |
| 资源清理 | 卸载时关闭在途 judge handle（close 被调用） |

## Mock 清单（均 `vi.hoisted` + `vi.mock`）

- `@/lib/notebook-api`（lookup/update/upsert/listCategories/addEntry/createCategory）
- `@/lib/session-api`（recordQuizResults）
- `@/lib/quiz-judge`（startQuizJudge / readFileAsBase64）
- `@/context/QuizFollowupContext`（controller stub + 空线程表）
- `@/components/common/MarkdownRenderer`（文本透传，避免 react-markdown/KaTeX 入 jsdom）

真实保留：Tooltip、CategoryMenu、i18n(en)、quiz-question-type 判定逻辑。

## 运行与数字

```bash
cd web
./node_modules/.bin/vitest run tests/quiz/QuizViewer.smoke.spec.tsx
#   Test Files  1 passed (1)
#   Tests       11 passed (11)   (~1.4s)

./node_modules/.bin/vitest run
#   Test Files  114 passed (114)
#   Tests       482 passed (482)  （含本文件 11 例，无回归）
```

- ESLint：`eslint tests/quiz/QuizViewer.smoke.spec.tsx` 通过。
- `node ./scripts/typecheck.mjs` 通过。
- 运行环境：worktree 内 `web/node_modules` 软链到主检出（本地 main 仅多一个
  `qrcode.react` 依赖，其余与 `ef2d9e5c3` lockfile 一致；未改动主检出任何文件）。

## 备注

- 全程未向上游开 PR；分支已推 `myfork`。
- 与既有失败无关：本套件不触碰 evidence 中列出的已知后端失败用例。

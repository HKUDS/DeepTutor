# DeepTutor i18n 体系导读

基线：`origin/main @ ef2d9e5c3`（v1.6.12）。本导读只读代码，不含任何改动。

## 0. 一图总览：两套体系、四块拼图

DeepTutor 的 i18n 不是一套系统，而是**两条独立链路 + 三块后端拼图**：

```
链 A（UI locale，界面文字）                          链 B（response language，模型输出语言）
web/locales/*.json (i18next)                        interface.json: response_language
   ↑ localStorage deeptutor-language                   ↑ localStorage deeptutor-response-language
   ↑ GET /api/settings/ui                              ↑ 每次 start_turn payload.language
   └→ AppShellContext → I18nProvider                   └→ request_preparer → UnifiedContext.language
                                                          ├→ PromptManager 选 prompts/{en,zh}/*.yaml
后端 UI locale 消费者（读 interface.json: language）         ├→ StatusI18n 选 status 文案
├─ deeptutor/services/i18n.py   API/CLI 错误文案           └→ language_directive 拼进 system prompt
└─ deeptutor/runtime/banner.py  CLI banner
静态元数据（不经存储，随请求参数选语言）
└─ deeptutor/i18n/metadata_i18n.py 能力/工具描述
```

**两套的关系（验收点 1）**：后端 i18n（Python 侧）与 web localization（i18next）是**两套互不消费的键空间**——web 不读 `_MESSAGES`，后端不读 `web/locales/`。它们只通过 `data/user/settings/interface.json` 里的两个字段发生关系：`language`（UI locale，5 种）与 `response_language`（输出语言，15 种）。这两个字段曾是一个 `language`，拆分后老文件靠 `resolve_languages` 继承迁移（`deeptutor/services/settings/interface_settings.py:143-162`）。浏览器侧对应两个 localStorage 键（`web/context/app-shell-storage.ts:74-75`），AppShell 启动时一次 fetch 同时采纳两个字段（`web/context/AppShellContext.tsx:106-174`）。

## 1. 后端拼图一：运行时文案 `deeptutor/services/i18n.py`

最小的内置字典翻译器，服务 API 路由与 CLI 的**面向用户错误消息**（partner/persona/soul/MCP/sandbox/cli_apps 等）。

- `_parse_language`（`deeptutor/services/i18n.py:8-12`）：非 zh 系一律归 `en`——注意 `fr/de/uk` 的 UI locale 在这层**会被当作 en**，因为 `_MESSAGES` 只有 en/zh 两份（`deeptutor/services/i18n.py:15-110`）。
- `current_language()`（`deeptutor/services/i18n.py:113-119`）：惰性 import `get_ui_language()` 读 `interface.json` 的 `language`，任何异常静默回 `en`。
- `t(key, default, language=None, **kwargs)`（`deeptutor/services/i18n.py:122-130`）：回退顺序 `目标语言 → en → default`；`str.format` 占位符渲染失败时原样返回文本，不抛异常。
- 消费方：`deeptutor/api/routers/partners.py`、`personas.py`、`space_mcp.py`、`space_cli_apps.py`、`mcp_settings.py`、`deeptutor/services/sandbox/service.py`、`deeptutor/tools/exec_tool.py`、`deeptutor/services/cli_apps/runner.py` 等。

## 2. 后端拼图二：提示词与状态文案（PromptManager / StatusI18n / language.py）

这是"模型响应语言"链路的主体，YAML 文件按语言分目录：

- 文件布局：`deeptutor/agents/<module>/prompts/{en,zh}/<name>.yaml`；非 agents 模块走 `NON_AGENT_MODULES` 映射（`deeptutor/services/prompt/manager.py:43-51`），如 `mastery → deeptutor/capabilities/mastery/prompts/`、`capabilities → deeptutor/capabilities/prompts/`。legacy `src/` 与 `deeptutor/` 双根都会尝试（`manager.py:140-152`）。
- `PromptManager.load_prompts(module, agent, language)`（`deeptutor/services/prompt/manager.py:58-89`）：单例 + 按 `(module, agent, lang)` 缓存；**空结果不缓存**（`manager.py:83-89`，避免打包缺资源被永久记住）。`clear_cache` 见 `manager.py:218`。
- 回退链（`manager.py:127-138`）：`[请求语言自身] + LANGUAGE_FALLBACKS（zh→[zh,cn,en]、en→[en,zh,cn]，manager.py:23-26）+ "en"` 兜底。注释引用 #712：**语言指令才是让模型用该语言作答的机制，提示词文件不是**——所以 ja/ko 请求落到 en 提示词文件是预期行为。
- `StatusI18n`（`deeptutor/i18n/status_i18n.py:23-57`）：能力 `run()` 顶部构造一次（如 `deeptutor/agents/question/capability.py:45`，`deeptutor/capabilities/audio_overview/capability.py:40`），读 YAML 顶层 `status:` 映射（例如 `deeptutor/agents/question/prompts/en/deep_question.yaml:1`、`deeptutor/capabilities/prompts/en/audio_overview.yaml:29`），`t(key, default, **kwargs)` 键缺/非字符串即回 `default`（`status_i18n.py:49-57`）。惰性 import PromptManager 是为打断 bootstrap 期的循环依赖（`status_i18n.py:34-39`）。
- 语言指令（`deeptutor/services/prompt/language.py`）：`language_directive`（`language.py:62-103`）生成"全部面向读者文本必须用 X 语言"的硬指令；`allow_user_override=True`（对话型界面）额外加一句"用户当次明确要求可改语言"（`language.py:51-59`），书籍/试卷/报告等无人在环的场景保持严格式。`append_language_directive`（`language.py:106-117`）把它拼到 system prompt 末尾。`is_chinese`/`language_label`/`normalize_language`（`language.py:30-48`）是各模块共用的判定件。

## 3. 后端拼图三：静态元数据 `deeptutor/i18n/metadata_i18n.py`

能力/工具的展示描述字典（en+zh 内联），供设置页与 API：`capability_description_i18n` / `tool_description_i18n`（`deeptutor/i18n/metadata_i18n.py:80-91`）未知名字回 `{"en": fallback, "zh": fallback}`；`localized_description`（`metadata_i18n.py:94-96`）按 `lang → en → zh → ""` 取值。这块**不读任何存储**，语言由调用方直接传参。

## 4. Web 侧 localization 加载

技术栈 i18next + react-i18next，单命名空间 `app`：

- `initI18n`（`web/i18n/init.ts:12-37`）：模块加载时只注册 `en` bundle；`fallbackLng: "en"`、`keySeparator: false`（"Generating..." 这类整句也算键）、`returnEmptyString: false` / `returnNull: false`（空值视为缺键落到英文）。
- 懒加载 `ensureLanguage`（`web/i18n/init.ts:39-57`）：切换到 `zh/fr/de/uk` 时才动态 `import()` 对应 bundle。locale 目录现实：`web/locales/{en,zh,fr,de}/` 各有 `app.json + common.json`，`web/locales/uk/` 只有 `app.json`。
- 语言归一 `normalizeLanguage`（`web/i18n/languages.ts:20-29`）：未知一律 `en`；可选语言白名单 `APP_LANGUAGES`（`languages.ts:2-8`，en/zh/fr/de/uk）。
- `I18nProvider`（`web/i18n/I18nProvider.tsx`）：模块顶层先 `initI18n()`（`:20`，避免渲染期触发 i18next 事件）；effect 里 `ensureLanguage → changeLanguage → 同步 <html lang>`（`:40-56`）；bundle 未就绪前渲染空壳而非半翻译 UI（`:58-66`）。开关由 `I18nClientBridge`（`web/i18n/I18nClientBridge.tsx:6-13`）从 AppShell 拿 `language + languageReady`。
- 语言来源（`web/context/AppShellContext.tsx:106-174`）：先读 localStorage `deeptutor-language`；本浏览器没选过才 `GET /api/settings/ui` 采纳账号设置（1.5s 超时兜底）；两个语言键一次 fetch 一起采纳，`response_language` 缺失时按"继承 interface locale"解析，与服务端老文件迁移语义一致。`setLanguage` 只写 localStorage 并广播（`AppShellContext.tsx:279-281`）；设置页经 `web/lib/settings-extensions.ts:17`（`/api/settings/ui`）持久化到后端。

## 5. 语言协商时序（验收点：UI locale 与模型响应语言的关系)

链 B 的完整时序（每一次对话回合）：

1. **浏览器出价**：`ChatStateAdapter` 每次发起回合从 localStorage 读 `deeptutor-response-language` 放进 payload（`web/features/chat/ChatStateAdapter.tsx:2536`、`:2577`；组装见 `web/features/chat/controllers/buildStartTurnInput.ts:78-80`，同时可带 `reply_language_override`）。
2. **后端默认值**：`RequestPreparer.start_turn` 里 payload 无 `language` 时补账号默认 `get_response_language()`（`deeptutor/services/session/turns/request_preparer.py:151-156`）。
3. **会话级覆盖**：会话偏好里的 `reply_language_override` 优先于账号默认与浏览器出价，且只有 selector 的显式字段能改/清它（#1511，`request_preparer.py:177-186`；写入口 `deeptutor/api/routers/sessions.py:346`，合法性校验 `sessions.py:16,:64` → `deeptutor/core/response_languages.py:22-27`，非法值直接 `ValueError`，这是全链路唯一"报错不回退"的口）。
4. **进上下文**：executor 组 `UnifiedContext(language=payload...)`（`deeptutor/services/session/turns/executor.py:884-896`），并把 `reply_language_fixed` 塞进 metadata（`executor.py:922`）。`UnifiedContext.language` 字段定义在 `deeptutor/core/context.py:138`。
5. **双消费**：能力用 `context.language` 构造 `StatusI18n` 选进度文案（en/zh 文件，其他语言落 en）；同时 `language_directive` 把输出语言硬指令拼进 system prompt（15 种语言全支持，标签表 `language.py:10-27`，支持域 `deeptutor/core/response_languages.py:3-19`）。

与链 A 的关系一句话：**UI locale 决定"界面说什么语言"，response language 决定"模型答什么语言"**；两者在设置里并存、可不同（例如英文界面 + 中文回答）。response_language 是从 `language` 拆出来的后起字段，老数据自动继承（`interface_settings.py:143-162`）。`get_ui_language` / `get_response_language` 是两条链各自的唯一读取口（`deeptutor/services/settings/interface_settings.py:295-305`、`:308-311`），全部下游都汇聚于此。CLI banner 走链 A（`deeptutor/runtime/banner.py:475-499`）；mastery/question/co_writer/quiz_judge 等路由走链 B 调 `get_response_language`。

## 6. 键生命周期：新增东西分别要动哪里

| 场景 | 必改位置 | 备注 |
| --- | --- | --- |
| 加 web UI 键 | `web/locales/en/app.json` + `web/locales/zh/app.json` | `npm run i18n:parity` 强制 en/zh 文件与键集一致；fr/de/uk 允许 per-key 回退 en |
| 加后端 API 文案 | `deeptutor/services/i18n.py` `_MESSAGES` 的 en+zh 两块 + `t("key", default)` 调用 | zh 缺键静默显英文 |
| 加能力 status 文案 | 对应 `prompts/{en,zh}/<name>.yaml` 顶层 `status:` + 代码 `i18n.t("key", "英文默认")` | default 保证翻译缺位时不空 |
| 加 UI 语言 | `web/locales/<lc>/`、`web/i18n/init.ts:ensureLanguage` 分支、`web/i18n/languages.ts:APP_LANGUAGES`、`interface_settings._normalize_language` 白名单 | 后端 `_normalize_language`（`interface_settings.py:81-114`）是"这个语言存在与否"的门；`services/i18n.py` 若需后端文案也要加 |
| 加 response 语言 | `deeptutor/core/response_languages.py:3-19`、`interface_settings._RESPONSE_LANGUAGE_ALIASES`（`:38-55`）、`language.py:_LANGUAGE_LABELS`（`:10-27`） | 提示词文件仍只有 en/zh，靠指令出该语言 |

## 7. 缺键回退行为（逐层）

| 层 | 位置 | 行为 |
| --- | --- | --- |
| web i18next | `web/i18n/init.ts:22-32` | `fallbackLng "en"`；空串/null 视为缺键 |
| web 语言归一 | `web/i18n/languages.ts:20-29` | 未知 → en |
| 后端 API 文案 | `deeptutor/services/i18n.py:124` | 目标语言 → en → `default` 参数 |
| 后端语言判定 | `deeptutor/services/i18n.py:8-12` | 非 zh 系 → en（fr/de/uk 在此层被折叠） |
| StatusI18n | `deeptutor/i18n/status_i18n.py:49-57` | 键缺/非字符串 → `default` |
| PromptManager 文件 | `deeptutor/services/prompt/manager.py:127-138` | 请求码 → 别名链 → en 兜底（#712）；空结果不缓存（`:83-89`） |
| `parse_language` | `deeptutor/services/config/loader.py:171+` | en/english、zh/cn/chinese 折叠；其他码透传（ja 保持 ja 不塌成 zh） |
| metadata | `deeptutor/i18n/metadata_i18n.py:80-96` | 未知名 → 双语 fallback；取值 lang→en→zh |
| interface.json 读取 | `deeptutor/services/settings/interface_settings.py:176-181` | 解析异常 → 全量默认值 |
| UI 语言白名单 | `interface_settings.py:81-114` | 未知码 → default（静默当英文） |
| response 语言 | `interface_settings.py:117-140` | 别名表 → 支持表 → base 码 → fallback |
| 会话覆盖校验 | `deeptutor/core/response_languages.py:22-27` | 非法值 `ValueError`（唯一硬失败点） |

## 8. 排查点（症状 → 先看哪里）

- zh 用户看到英文按钮/文案 → `npm run i18n:parity` 查 zh 键缺失；再跑 `npm run i18n:audit` / eslint `no-literal-ui-text`（`web/eslint/i18n-plugin.mjs`）查硬编码。
- 中文环境 API 报错是英文 → `_MESSAGES["zh"]` 缺键，或 `t()` 未走到 `current_language()`（`interface.json` 读失败会静默回 en）。
- ja/ko 用户进度条是英文 → 预期行为：prompts 只有 en/zh，回退链落 en（#712），输出语言靠指令保证。
- 模型全程答英文 → 顺链查：localStorage `deeptutor-response-language` → payload.language → 会话 `reply_language_override` 是否把语言钉死 → `append_language_directive` 是否拼上。
- 新加语言不生效 → `interface_settings._normalize_language` 白名单、web `APP_LANGUAGES`、`ensureLanguage` 分支，三者缺一即静默回英文。
- 改了 yaml 不生效 → PromptManager 按 `(module, agent, lang)` 缓存，改文件需 `clear_cache` 或重启（`manager.py:218-230`）。

## 9. 与既有 scan-i18n 扫描卡的衔接点

- 扫描卡产物：分支 `pr/scan-i18n-en-zh-audit`（AGEN-460，commit `3faaacf0f`）下的 `evidence/i18n-scan-2026-10-04/`：`report.md`、`missing_keys_list.txt`（缺键清单）、`zh_untranslated_echo.txt`（zh 回显英文）、`cjk_hardcoded_list.txt`（硬编码中文）、`scan_i18n.py`（扫描脚本）。
- **缺键清单 ↔ 本导读第 7 节**：扫描出的"缺键"在本体系里从不表现为崩溃，而是**静默回退英文/默认值**（i18next `fallbackLng`、`t(key, default)`）——所以修复优先级应按"用户可见度"排，且 parity 工具必须在 CI 兜住增量。
- **zh_untranslated_echo ↔ 回退链**：这些"中文包里出现英文值"与第 7 节的各层回退是两类问题——前者是翻译债，后者是设计行为，修复手法不同。
- **cjk_hardcoded ↔ 存量入口**：硬编码清单是 `web/scripts/i18n_audit.mjs`（启发式扫描，`--strict` 门禁）与 eslint 规则的存量来源；增量靠 `web/package.json:19` 的 `check:fast`（含 `i18n:check` = parity + audit，`:23-26`）和测试 `web/tests/i18n-placeholders.test.ts`、`web/tests/i18n-audit.spec.ts`、`web/tests/workspace-i18n.spec.ts` 把关。
- 后续修复卡的验收命令建议：`cd web && npm run i18n:check`；后端文案改动跑 `timeout 900 python -m pytest deeptutor -q -p no:cacheprovider -k i18n`。

## 10. 本导读验证方式

只读产出：`git diff origin/main` 仅含 `evidence/` 新增文件；未改任何代码。锚点行号以 `origin/main @ ef2d9e5c3` 为准。

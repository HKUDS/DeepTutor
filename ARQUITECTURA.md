# DeepTutor — Análisis de arquitectura, librerías, funcionalidades y deuda técnica

> Análisis realizado sobre la rama `dev`, commit `8865da7c` (v1.5.10).
> Ámbito: `deeptutor/`, `deeptutor_cli/`, `web/`, `tests/`, empaquetado y CI.

---

## 1. Resumen ejecutivo

DeepTutor es un **compañero de aprendizaje agent-native**: un backend Python (FastAPI + asyncio)
que orquesta LLMs, RAG, memoria y herramientas, más un frontend Next.js 16 / React 19, más un CLI
Typer, todo empaquetado como una sola distribución instalable (`pip install deeptutor`) o como
imagen Docker.

**Lo que está muy bien:**

- Arquitectura de plugins de dos niveles (Tools / Capabilities) genuinamente extensible, con
  protocolos explícitos (`BaseTool`, `BaseCapability`, `LoopCapability`) y registros centralizados.
- Un único punto de entrada lógico (`ChatOrchestrator`) compartido por CLI, WebSocket y SDK: no hay
  tres implementaciones divergentes del mismo turno.
- Aislamiento multi-usuario pensado desde el diseño (`UserScope`, árboles de workspace por usuario,
  grants, auditoría) en lugar de añadido a posteriori.
- Suite de tests grande (~73.000 líneas, ~380 ficheros) y densidad de documentación en el código
  muy por encima de la media: los comentarios explican el *porqué* y citan issues concretos.
- Sandbox de ejecución con selección de backend por nivel de aislamiento (sidecar → bwrap →
  subprocess), quotas por usuario y `exec` denegado por defecto si no hay aislamiento de sistema.
- Renderizado de HTML generado por el LLM en `<iframe sandbox="allow-scripts">` **sin**
  `allow-same-origin`, más una allowlist de etiquetas para Markdown. La superficie XSS está tratada.

**Lo que más preocupa:**

1. **CORS permisivo con credenciales** cuando `auth.enabled=false` (el modo por defecto).
2. **Configuración de auth congelada en tiempo de importación**: activar auth desde la UI no surte
   efecto hasta reiniciar el proceso.
3. **SQLite sin WAL ni `busy_timeout`**, con conexión nueva por operación y un `asyncio.Lock` global
   que serializa todo el almacén de sesiones.
4. **4.322 ficheros de build de Next.js versionados en git** pese a estar en `.gitignore`.
5. **CI sin type-check, sin lint de frontend, sin build de frontend, sin cobertura y sin escaneo de
   seguridad**, y ejecutándose solo en Ubuntu para un producto que se distribuye en Windows.
6. **Dos paquetes compiten por el mismo concepto** ("capability" vive a la vez en `deeptutor/agents/`
   y en `deeptutor/capabilities/`, con dos registros distintos).

---

## 2. Métricas del repositorio

| Métrica | Valor |
| --- | --- |
| Ficheros versionados | 6.240 (de los cuales **4.322 son output de build**) |
| Python de producción | ~148.400 líneas |
| Python de tests | ~73.100 líneas (`tests/` + `deeptutor/learning/tests`) |
| TypeScript / TSX | ~107.500 líneas |
| Componentes React | 258 `.tsx` — **238 llevan `"use client"`** |
| Routers FastAPI | 32 |
| Canales de Partners (IM) | 19 |
| Pipelines RAG | 6 (llamaindex, graphrag, lightrag, lightrag_server, pageindex, ima) |
| Prompts YAML i18n | 84 ficheros, paridad `en`/`zh` (64 dirs cada uno) |
| Marcadores TODO/FIXME | 3 (excelente) |
| `except Exception` | 884, de los cuales ~72 terminan en `pass` |
| `# type: ignore` | 55 |

**Distribución de LOC de producción por área:**

```
services/     65.196   ██████████████████████████
agents/       17.155   ███████
api/          15.693   ██████
partners/     12.252   █████
book/          7.685   ███
tools/         7.607   ███
cli/           5.136   ██
learning/      4.198   ██
core/          3.818   █
capabilities/  3.783   █
knowledge/     3.545   █
runtime/       3.192   █
multi_user/    2.031   █
```

---

## 3. Arquitectura

### 3.1 Visión de capas

```
┌───────────────────────────────────────────────────────────────────────┐
│  ENTRADAS                                                             │
│  CLI (Typer)      WebSocket /api/v1/ws      REST (32 routers)   SDK    │
│  deeptutor_cli/   api/routers/unified_ws    api/routers/*    app.py    │
└──────────┬────────────────┬────────────────────┬───────────────┬──────┘
           └────────────────┴──────────┬─────────┴───────────────┘
                                       ▼
                    ┌──────────────────────────────────┐
                    │      ChatOrchestrator            │  runtime/orchestrator.py
                    │  UnifiedContext → Capability     │  (147 líneas — muy fino)
                    │  gestiona el ciclo del StreamBus │
                    └───────┬──────────────────┬───────┘
                            ▼                  ▼
              ┌──────────────────┐   ┌────────────────────────┐
              │  ToolRegistry    │   │  CapabilityRegistry    │
              │  (Nivel 1)       │   │  (Nivel 2)             │
              └────────┬─────────┘   └───────────┬────────────┘
                       │                         │
        ┌──────────────┴──────┐      ┌───────────┴──────────────┐
        │ builtin │ MCP │ CLI │      │ chat · deep_solve ·      │
        │ apps    │     │apps │      │ deep_question ·          │
        └─────────────────────┘      │ deep_research ·          │
                                     │ visualize · math_animator│
                                     │ mastery_path             │
                                     └──────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────┐
│  SERVICIOS (65k LOC — el verdadero peso del sistema)                   │
│  llm · rag · memory · embedding · parsing · session · sandbox ·        │
│  mcp · skill · search · imagegen · videogen · voice · cron · config    │
└───────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────┐
│  PERSISTENCIA                                                         │
│  data/user/           workspace admin (settings JSON, KBs, sesiones)   │
│  data/users/<uid>/    un workspace por usuario no-admin                │
│  data/partners/<id>/  workspaces de usuarios sintéticos (bots IM)      │
│  data/system/         cuentas, grants, auditoría, secretos por owner   │
│  SQLite               sesiones, turnos, mensajes, eventos, notebooks   │
└───────────────────────────────────────────────────────────────────────┘
```

### 3.2 El modelo de plugins de dos niveles

**Nivel 1 — Tools** (`core/tool_protocol.py`). Funciones de un disparo que el LLM invoca vía
function-calling. Contrato mínimo: `get_definition() -> ToolDefinition` y `execute(**kw) -> ToolResult`.

Tres detalles de diseño destacables:

- **`raw_parameters`** permite pasar JSON Schema arbitrario sin pérdida — indispensable para
  adaptadores MCP cuyos schemas upstream no encajan en el modelo `ToolParameter`.
- **`deferred`** implementa *progressive disclosure*: el schema no entra en la lista de tools del
  turno; el prompt lleva una línea por tool diferida y el modelo carga el schema bajo demanda con
  `load_tools`. Es la respuesta correcta a la explosión de tokens cuando hay N servidores MCP.
- **`pause_for_user`** deja que un tool (`ask_user`) **pause el turno** y lo reanude con la respuesta
  del usuario sustituida en el cuerpo del mensaje de tool, en vez de terminar el turno y empezar otro.

Los tools se montan por contexto (`ToolMountFlags`): la presencia de una KB monta `rag`, la de
adjuntos monta `read_source`, la disponibilidad del sandbox monta `exec`/`code_execution`, etc.

**Nivel 2 — Capabilities** (`core/capability_protocol.py`). Pipelines multi-etapa que toman el turno
entero. Siete built-ins, todas convergiendo en `emit_capability_result()` para emitir el mismo sobre
(payload + `cost_summary` del `UsageTracker`).

**Nivel intermedio no documentado — LoopCapabilities** (`capabilities/protocol.py`). Un tercer
concepto: plugins que se enganchan *dentro* del bucle agéntico de chat (mastery, solve, obsidian,
subagent, explore_context), inyectando bloques de prompt y tools propios, con una bandera
`exclusive_tools` que reemplaza toda la superficie de tools del turno.

### 3.3 Flujo de un turno

```
Usuario ──► WS "message" ──► TurnRuntimeManager (persiste el turno, seq monotónico)
                                   │
                                   ▼
                          ChatOrchestrator.handle(UnifiedContext)
                                   │
                    crea StreamBus, register_bus(turn_id)
                                   │
                          capability.run(context, bus)  ── asyncio.Task
                                   │
              ┌────────────────────┴───────────────────┐
              │  AgentLoop (máx. 8 rondas por defecto) │
              │  1. ensamblar prompt (ChatPromptAssembler)
              │  2. llamada LLM en streaming
              │  3. dispatch de tools en paralelo (MAX_PARALLEL_TOOL_CALLS)
              │  4. sin tool calls ⇒ fin del bucle
              └────────────────────┬───────────────────┘
                                   ▼
              bus.emit(...) ──► fan-out a suscriptores (cola por suscriptor)
                                   │
                  ┌────────────────┼─────────────────┐
                  ▼                ▼                 ▼
            WebSocket push   persistencia DB   renderer CLI
```

Puntos fuertes del diseño: `subscribe()` hace *replay* del historial en el mismo paso síncrono en el
que registra la cola, lo que evita la carrera clásica de entregar eventos dos veces; y el
`register_bus(turn_id)` permite que un mensaje `user_input` del WebSocket encuentre el bus del turno
correcto sin acoplar el router al orquestador.

### 3.4 Aislamiento multi-usuario

`multi_user/paths.py` resuelve un `UserScope` por petición y todo el I/O cuelga de `scope.root`.
Los admins operan sobre `data/`; los usuarios normales sobre `data/users/<uid>/`. `data/system/`
guarda cuentas, grants y secretos por owner con `chmod 0700`, y está explícitamente excluido del
montaje del runner del sandbox. Hay migración idempotente desde el layout `multi-user/` pre-v1.5.

Los grants (`multi_user/grants.py` + `*_access.py`) controlan qué modelos, KBs, skills, tools y
partners ve cada usuario. `conftest.py` incluso monta un guard que detecta si un test escribe en el
árbol real del desarrollador — un nivel de cuidado poco común.

---

## 4. Librerías y dependencias

### 4.1 Backend (Python ≥3.11, <3.14)

| Área | Librerías |
| --- | --- |
| **Web / API** | `fastapi`, `uvicorn[standard]`, `websockets`, `python-multipart` |
| **CLI / TUI** | `typer[all]`, `rich`, `prompt_toolkit`, `pyte` (emulador de terminal en memoria para *scrapear* el TUI `/model` de Claude Code) |
| **LLM** | `openai`, `anthropic`, `dashscope`, `perplexityai`, `tiktoken`, `oauth-cli-kit` |
| **RAG** | `llama-index` + BM25 + FAISS (`faiss-cpu`), opcional `graphrag`, `raganything`/LightRAG |
| **Documentos** | `PyMuPDF`, `pypdf`, `pdfplumber`, `python-docx`, `openpyxl`, `python-pptx`, `reportlab`, `defusedxml` |
| **Parsing opcional** | `markitdown`, `docling`, `pymupdf4llm` (motores intercambiables, import perezoso) |
| **Auth** | `bcrypt`, `python-jose[cryptography]`, `pocketbase` (backend de auth alternativo) |
| **Infra** | `pydantic` v2, `pydantic-settings`, `aiosqlite`, `tenacity`, `httpx`, `aiohttp`, `loguru`, `json-repair`, `nest_asyncio`, `croniter` |
| **Partners** | `python-telegram-bot`, `slack-sdk`, `lark-oapi`, `dingtalk-stream`, `qq-botpy`, `matrix-nio`, `zulip`, `wecom-aibot-sdk`, `mcp` |
| **Addons** | `manim` (math-animator) |

Sistema de extras bien pensado en `pyproject.toml`: `cli`, `server`, `partners`, `matrix`,
`matrix-e2e`, `math-animator`, `parse-*`, `graphrag`, `rag-lightrag`, `dev`, `all`. Los extras
pesados llevan marcadores `python_version < '3.14'` para que pip **no** retroceda silenciosamente a
una versión antigua del paquete cuando no hay wheel — es un detalle que casi nadie acierta.

### 4.2 Frontend (Next.js 16 / React 19)

| Área | Librerías |
| --- | --- |
| **Framework** | `next@16`, `react@19`, `tailwindcss@3`, `tailwind-merge`, `clsx` |
| **Markdown / mates** | `react-markdown`, `remark-gfm`, `remark-math`, `rehype-katex`, `rehype-raw`, `react-syntax-highlighter` |
| **Visualización** | `chart.js` + `react-chartjs-2`, `mermaid`, `cytoscape` (grafo de memoria), `framer-motion` |
| **Documentos** | `docx-preview`, `exceljs`, `jspdf`, `html2canvas` |
| **i18n** | `i18next`, `react-i18next` (paridad `en`/`zh` verificada por script) |
| **Testing** | `@playwright/test` (proyecto `ui-audit`), runner de tests Node propio |

### 4.3 Duplicación de manifiestos

Las dependencias viven **dos veces**: en `pyproject.toml` (extras) y en `requirements/*.txt`
(Docker/CI). Los propios comentarios dicen "Mirrors requirements/partners.txt", es decir, la
sincronización es manual y nada la verifica. Igual pasa con el despliegue: **cinco** ficheros compose
(`compose.yaml`, `compose.codex-oauth.yaml`, `docker-compose.yml`, `docker-compose.dev.yml`,
`docker-compose.ghcr.yml`) y un `Dockerfile` de 503 líneas con 5 etapas.

---

## 5. Funcionalidades

### 5.1 Capacidades de aprendizaje

| Capability | Etapas |
| --- | --- |
| `chat` | exploring → responding (bucle agéntico único, por defecto) |
| `mastery_path` | Guided Learning: bucle de chat + tools de maestría, gated por tipo de tema |
| `deep_solve` | planning → reasoning → writing |
| `deep_question` | ideation → generation (generación de preguntas / banco) |
| `deep_research` | rephrasing → decomposing → researching → reporting (con gestor de citas) |
| `visualize` | analyzing → generating → reviewing (SVG / Chart.js / Mermaid / HTML) |
| `math_animator` | concept_analysis → design → codegen → retry → summary → render (Manim) |

### 5.2 Otros subsistemas

- **Book engine** (`deeptutor/book/`, 7.685 LOC): generación de libros de texto interactivos con
  ~15 tipos de bloque (quiz, flashcards, timeline, grafo de conceptos, deep-dive, animación).
- **Memory** (42 ficheros): memoria en tres niveles (L1/L2/L3) con grafo navegable en la UI.
- **Knowledge bases**: 6 pipelines RAG intercambiables, versionado de índice, firma de embedding
  para invalidar índices al cambiar de modelo, KBs enlazadas.
- **Partners**: compañeros conectados a 19 plataformas de mensajería, cada uno como usuario
  sintético con su propio workspace y sus propios grants.
- **Skills**: sistema tipo `SKILL.md` con hub, instalación y control de acceso por usuario.
- **MCP**: cliente completo con tools diferidas y configuración por usuario.
- **CLI apps**: integración con Claude Code, Codex, Gemini, Kimi, MiMo, OpenCode — incluida
  autenticación OAuth de Codex por cuenta.
- **Co-writer**, **notebook**, **personas**, **cron**, **voz (STT/TTS)**, **imagegen**, **videogen**,
  **importación de conversaciones** desde Claude Code y Codex.

---

## 6. Fallos y debilidades

Ordenados por severidad. Cada uno con su ubicación.

### 🔴 Críticos

#### F1 — CORS permisivo con credenciales en el modo por defecto

[`deeptutor/api/main.py:107`](deeptutor/api/main.py:107) y [`:308`](deeptutor/api/main.py:308)

```python
allow_origin_regex = None if auth_settings["enabled"] else r"https?://.*"
...
allow_credentials=True,
```

Con `auth.enabled=false` (**el valor por defecto**), el backend acepta peticiones credenciadas desde
**cualquier origen**. Como en ese modo `require_auth` es un no-op y todo request se trata como admin,
cualquier página web que el usuario visite mientras DeepTutor corre en `localhost:8001` puede leer su
historial de chat, sus KBs, su memoria, y disparar tools — incluido `exec` si el sandbox está activo.

El comentario del código justifica esto como "compatibilidad con Docker/LAN pre-v1.3.8". Es un
trade-off consciente, pero la combinación regex-comodín + `allow_credentials=True` es precisamente el
patrón que el spec de CORS prohíbe con `*` por esta misma razón.

**Arreglo:** restringir el regex a rangos privados/loopback (`https?://(localhost|127\.0\.0\.1|\[::1\]|10\.…|192\.168\.…)(:\d+)?`)
y exigir `CORS_ORIGINS` explícito para cualquier otro origen, con o sin auth.

#### F2 — La configuración de auth se congela al importar el módulo

[`deeptutor/services/auth.py:39-60`](deeptutor/services/auth.py:39)

```python
_AUTH_SETTINGS = load_auth_settings()          # a nivel de módulo
AUTH_ENABLED: bool = bool(_AUTH_SETTINGS["enabled"])
```

`AUTH_ENABLED` es un valor de módulo leído una sola vez en el import. Consecuencias:

- Activar auth desde `/settings` **no protege nada** hasta reiniciar el proceso, y el usuario no
  recibe ninguna señal de eso.
- Lo mismo aplica a `_SECURE`/`_SAMESITE` en [`routers/auth.py:29`](deeptutor/api/routers/auth.py:29)
  y a la decisión de CORS, calculada una vez en el import de `main.py`.
- Los tests tienen que hacer monkeypatch de globales de módulo en vez de inyectar configuración.

**Arreglo:** convertir `AUTH_ENABLED` en una función (`auth_enabled()`) o en una dependencia FastAPI
que lea un `RuntimeSettingsService` cacheado con invalidación en `save_auth()`. Si se prefiere no
tocarlo, al menos que `save_auth()` avise en la UI de que hace falta reiniciar.

### 🟠 Altos

#### F3 — SQLite sin WAL, sin `busy_timeout`, y serializado por un lock global

[`deeptutor/services/session/sqlite_store.py:398-416`](deeptutor/services/session/sqlite_store.py:398)

```python
async def _run(self, fn, *args):
    async with self._lock:                    # ← serializa TODO el almacén
        return await asyncio.to_thread(fn, *args)

@contextmanager
def _connect(self):
    conn = sqlite3.connect(self.db_path)      # ← conexión nueva por operación
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # ← único PRAGMA
```

Tres problemas encadenados:

1. **Sin `journal_mode=WAL`**: los lectores bloquean a los escritores. Con el proceso de partners y
   el de API tocando la misma DB, aparecen `database is locked`.
2. **Sin `busy_timeout`**: se usa el default de 5 s, sin reintento explícito ni mensaje útil.
3. **`asyncio.Lock` que envuelve el `to_thread` entero**: no hay *ninguna* concurrencia en el almacén
   de sesiones dentro de un proceso. Cada evento de stream persistido de cada turno de cada usuario
   hace cola detrás de todos los demás. En un turno agéntico con muchos tool calls esto es el camino
   caliente.

**Arreglo:** `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000` en
`_connect`; un pool de conexiones (o una conexión por hilo con `check_same_thread=False`); y sustituir
el lock global por locks a nivel de escritura, dejando las lecturas en paralelo.

#### F4 — 4.322 ficheros de build versionados en git

`web/.next-deeptutor/` está en [`.gitignore:79`](.gitignore:79) **y a la vez versionado**: 4.322 de
los 6.240 ficheros del repo (69%) son output de compilación de Next.js, incluidos chunks minificados,
el bundle `standalone` completo y assets duplicados.

Efectos: clones lentos, diffs ilegibles, conflictos de merge en artefactos, y el riesgo real de que
el build versionado y el código fuente se desincronicen. El último commit que tocó `BUILD_ID` es un
refactor de auth (`b7b15ccc`), lo que confirma que se recomitan en cambios de código no relacionados.

**Arreglo:** `git rm -r --cached web/.next-deeptutor`, construir en CI, y publicar los assets en el
wheel desde el artefacto del build (que es lo que `package-data` de `deeptutor_web` ya espera).

#### F5 — Huecos serios en CI

[`.github/workflows/tests.yml`](.github/workflows/tests.yml)

El pipeline ejecuta: ruff (lint + format), tests Node del frontend, import-check y pytest. **Falta:**

| Ausente | Riesgo |
| --- | --- |
| `tsc --noEmit` | 107k líneas de TS con `strict: true` y **nada** verifica los tipos en CI |
| `npm run lint` | ESLint está configurado pero no se ejecuta nunca |
| `next build` | Un fallo de build solo se descubre al publicar |
| Cobertura | 73k líneas de test y ninguna métrica de qué cubren |
| `bandit` / `safety` | Están en las deps de `dev` pero no hay job que los invoque |
| Matriz de SO | Solo `ubuntu-latest`, para un producto que se instala en Windows y macOS |
| Playwright `ui-audit` | Configurado en `package.json`, nunca ejecutado |

Además el perfil de ruff es deliberadamente laxo (solo `E`, `F`, `I` + `B006`) con `E501`, `E722` y
`E402` ignorados, y no hay comprobación de tipos en Python pese al uso intensivo de anotaciones.

### 🟡 Medios

#### F6 — Dos paquetes para el mismo concepto de "capability"

[`deeptutor/runtime/bootstrap/builtin_capabilities.py`](deeptutor/runtime/bootstrap/builtin_capabilities.py)

```python
"chat":          "deeptutor.agents.chat.capability:ChatCapability",
"deep_solve":    "deeptutor.capabilities.solve.capability:DeepSolveCapability",
"deep_question": "deeptutor.agents.question.capability:DeepQuestionCapability",
"mastery_path":  "deeptutor.capabilities.mastery.capability:MasteryPathCapability",
```

Cinco de siete capabilities viven en `deeptutor/agents/` y dos en `deeptutor/capabilities/`, sin una
regla que lo explique — y `AGENTS.md` documenta `deeptutor/capabilities/` como "implementaciones de
capabilities built-in", lo cual solo es cierto para dos de ellas.

Peor: existen **dos registros** que no son lo mismo pero comparten nombre:

- `runtime/registry/capability_registry.py` → capabilities del orquestador.
- `capabilities/registry.py` → `LoopCapabilities`, plugins *dentro* del bucle de chat.

Un lector nuevo no puede saber qué "capability" significa sin abrir ambos ficheros.

**Arreglo:** mover todas las capabilities del orquestador a `deeptutor/capabilities/`, dejar
`deeptutor/agents/` para los pipelines internos que ellas usan, y renombrar `LoopCapability` a algo
sin colisión (`ChatExtension`, `LoopPlugin`).

#### F7 — `StreamBus`: historial ilimitado y colas sin backpressure

[`deeptutor/core/stream_bus.py:44`](deeptutor/core/stream_bus.py:44)

```python
self._history.append(event)                   # nunca se poda
for q in self._subscribers:
    await q.put(event)                        # asyncio.Queue() sin maxsize
```

- `_history` guarda **todos** los eventos del turno en memoria para el replay. Un turno de research
  con muchos tool results puede acumular megabytes; nada lo limita ni lo trunca.
- Las colas de suscriptor no tienen `maxsize`, así que un consumidor WebSocket lento no ejerce
  backpressure: el productor sigue emitiendo y la memoria crece.
- `emit()` descarta en silencio si el bus está cerrado — un evento perdido no deja rastro.
- [`submit_input():294`](deeptutor/core/stream_bus.py:294) hace `self._input_listeners.clear()` tras
  entregar a **todos** los waiters: con dos pausas `ask_user` concurrentes, ambas reciben la misma
  respuesta.

#### F8 — Ficheros-dios

| Fichero | Líneas |
| --- | --- |
| `deeptutor/api/routers/knowledge.py` | 2.940 |
| `deeptutor/agents/research/pipeline.py` | 2.871 |
| `web/components/chat/home/TracePanels.tsx` | 2.696 |
| `web/app/(workspace)/co-writer/[docId]/page.tsx` | 2.495 |
| `web/app/(workspace)/home/[[...sessionId]]/page.tsx` | 2.339 |
| `deeptutor/agents/question/pipeline.py` | 2.161 |
| `deeptutor/services/session/turn_runtime.py` | 2.128 |
| `web/context/UnifiedChatContext.tsx` | 2.003 |
| `deeptutor/services/session/sqlite_store.py` | 1.902 |

Un router de 2.940 líneas no es un router: es un subsistema completo dentro de un módulo. Lo mismo
para un componente React de 2.696 líneas. Son los puntos donde el coste de cambiar crece más rápido.

#### F9 — El frontend App Router usado como SPA

238 de 258 componentes `.tsx` llevan `"use client"` (92%). Next.js 16 se está usando esencialmente
como un bundler de SPA: se paga el coste conceptual del App Router sin obtener React Server
Components, streaming de servidor ni reducción de bundle. Dado que el backend es Python, la parte
de servidor de Next tampoco puede hacer data fetching real — pero entonces la pregunta legítima es si
Vite + React Router no sería una elección más honesta y más rápida de compilar.

#### F10 — 884 `except Exception`, 72 terminando en `pass`

Muchos son deliberados y están comentados (probes de disponibilidad de motores, imports opcionales),
lo cual es correcto. Pero 72 bloques que se tragan la excepción sin loguear nada convierten fallos
reales en comportamiento silencioso: un tool que falla al montar simplemente no aparece, sin pista
para el usuario ni para el desarrollador.

**Arreglo:** una regla — `except Exception: pass` solo se permite con un `logger.debug(...,
exc_info=True)` dentro. Es un cambio mecánico y `ruff` puede vigilarlo (`BLE001`, `S110`).

### 🔵 Bajos / higiene

- **F11 — Manifiestos de dependencias duplicados.** `pyproject.toml` extras vs `requirements/*.txt`
  sincronizados a mano ("Mirrors requirements/partners.txt") sin ninguna verificación en CI.
- **F12 — Cinco ficheros compose + Dockerfile de 503 líneas.** El solapamiento entre `compose.yaml` y
  `docker-compose.yml` no está documentado en ningún sitio evidente.
- **F13 — Sin cabeceras de seguridad.** `web/next.config.js` no define `headers()`: no hay CSP,
  `X-Frame-Options`, `Referrer-Policy` ni `X-Content-Type-Options`.
- **F14 — Claves de API en JSON plano.** `data/user/settings/*.json` guarda `api_key` sin cifrar.
  `atomic_write_json` hereda el modo 0600 de `NamedTemporaryFile`, lo que mitiga en POSIX, pero no en
  Windows. No hay integración con keyring del sistema.
- **F15 — Docs dispersos en la raíz.** 7 `.md` en el nivel superior (`README.md` de 871 líneas,
  `AGENTS.md`, `CONTAINERIZATION.md`, `SKILL.md`, `Communication.md` de 233 bytes…) sin un `docs/`
  que los organice.
- **F16 — Singletons instanciados en import.** `LOOP_CAPABILITIES` en
  [`capabilities/registry.py:13`](deeptutor/capabilities/registry.py:13) construye las cinco
  instancias en tiempo de import y las comparte entre todos los usuarios y turnos. Hoy son stateless,
  pero nada en el tipo lo impide: el día que una guarde estado, será un bug de fuga entre usuarios
  difícil de diagnosticar.
- **F17 — `time.sleep()` en canales de partners.** `feishu.py:380`, `zulip.py` (7 ocurrencias) usan
  sleep bloqueante; si corren en el event loop, congelan el proceso durante segundos.

---

## 7. Cómo podría ser mejor

### Fase 1 — Seguridad y corrección (1–2 semanas)

| # | Acción | Resuelve |
| --- | --- | --- |
| 1 | Acotar el regex de CORS a loopback/rangos privados y exigir `CORS_ORIGINS` explícito para el resto, con y sin auth | F1 |
| 2 | Sustituir `AUTH_ENABLED` y demás globales de import por lecturas de configuración en runtime con invalidación de caché al guardar | F2 |
| 3 | `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` + `busy_timeout=5000`; pool de conexiones; lock solo de escritura | F3 |
| 4 | Añadir `headers()` en `next.config.js` con CSP, `X-Frame-Options: DENY`, `Referrer-Policy`, `X-Content-Type-Options` | F13 |
| 5 | Añadir jobs de `bandit` y `pip-audit` al pipeline | F5 |

### Fase 2 — Blindaje del pipeline (1 semana)

| # | Acción | Resuelve |
| --- | --- | --- |
| 6 | `git rm -r --cached web/.next-deeptutor` + build de frontend en CI + publicación desde artefacto | F4 |
| 7 | Añadir a CI: `tsc --noEmit`, `npm run lint`, `next build` | F5 |
| 8 | Cobertura con `pytest-cov` y un umbral que no baje (no un número aspiracional) | F5 |
| 9 | Matriz de CI con `windows-latest` y `macos-latest` para al menos import-check y el subconjunto de tests que toca rutas | F5 |
| 10 | Un test que verifique que `pyproject.toml` y `requirements/*.txt` no han divergido | F11 |

### Fase 3 — Claridad arquitectónica (2–4 semanas)

| # | Acción | Resuelve |
| --- | --- | --- |
| 11 | Unificar capabilities en un solo paquete; renombrar `LoopCapability` → `ChatExtension` | F6 |
| 12 | Poner cota al `_history` del `StreamBus` (ventana de N eventos o volcado a disco) y `maxsize` a las colas de suscriptor | F7 |
| 13 | Arreglar `submit_input` para entregar a un solo waiter (cola FIFO en vez de broadcast + clear) | F7 |
| 14 | Trocear `knowledge.py` en `routers/knowledge/{crud,ingest,query,engines}.py` — el router debe validar y delegar, no implementar | F8 |
| 15 | Extraer `TracePanels.tsx` y `UnifiedChatContext.tsx` en módulos por responsabilidad | F8 |
| 16 | Regla de lint: `except Exception: pass` requiere `logger.debug(exc_info=True)` | F10 |

### Fase 4 — Estratégico (evaluar, no ejecutar a ciegas)

- **Postgres opcional para sesiones.** SQLite es la elección correcta para el caso single-user y para
  el "zero-config" que el proyecto promete. Pero el modo multi-usuario con partners escribiendo desde
  otro proceso ya está estirando lo que SQLite da cómodamente. La abstracción `SessionStoreProtocol`
  ya existe: añadir un backend Postgres es incremental, no una reescritura.
- **Revisar la elección de Next.js.** Con 92% de componentes cliente, el App Router no está aportando
  lo que cuesta. Migrar a Vite + React Router reduciría tiempo de build y complejidad conceptual — o,
  alternativamente, invertir en mover partes reales a Server Components. Lo que no tiene sentido es
  quedarse en el punto intermedio actual.
- **Type-checking gradual en Python.** `mypy --strict` sobre `core/` y `runtime/` primero (son
  pequeños, estables y ya están bien anotados), extendiendo hacia `services/` por módulos.
- **Consolidar el despliegue.** Un `compose.yaml` con perfiles (`--profile dev`, `--profile ghcr`)
  en lugar de cinco ficheros, y trocear el `Dockerfile` de 503 líneas.
- **Presupuesto de rendimiento del turno.** El bucle agéntico tiene un tope de 8 rondas y un
  `UsageTracker`, pero no hay tracing end-to-end (`OpenTelemetry`) para responder a "¿dónde se fueron
  los 40 segundos de este turno?".

---

## 8. Veredicto

Es un proyecto **maduro y con criterio de ingeniería visible**. Las abstracciones centrales
—registro de tools con progressive disclosure, capabilities de dos niveles, `UnifiedContext`,
`StreamBus`, scopes multi-usuario— están bien elegidas y bien documentadas; los comentarios explican
decisiones y citan issues concretos, que es exactamente lo que hace mantenible un sistema de 148k
líneas. El aislamiento del sandbox y el tratamiento de HTML generado por LLM demuestran que se ha
pensado en seguridad donde más cuenta.

La deuda no está en el diseño sino **alrededor** de él: la configuración leída en tiempo de import,
el default de CORS, la ausencia de WAL, el build versionado y los huecos de CI son todos problemas de
*disciplina de infraestructura*, no de arquitectura. Son también, por eso mismo, baratos de arreglar
en relación con lo que aportan.

Las dos cosas que arreglaría primero, si solo hubiera tiempo para dos: **F1 (CORS)** porque es
explotable hoy en la configuración por defecto, y **F5 (CI)** porque sin type-check ni build del
frontend en el pipeline, cada release es una apuesta.

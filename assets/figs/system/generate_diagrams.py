"""Generate the README's current-dev engineering diagrams (stdlib only).

Run: python assets/figs/system/generate_diagrams.py
Sources: app/container.py, app/service.py, runtime/turn_engine.py,
runtime/orchestrator.py, core/stream.py, agents/_shared/capability_result.py.
The SVGs are editable text; no raster assets are modified.
"""

from html import escape
from pathlib import Path

ROOT = Path(__file__).parent


class Diagram:
    def __init__(self, title, description, height):
        self.height = height
        self.parts = [
            f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="{height}" viewBox="0 0 1280 {height}" role="img" aria-labelledby="title desc"><title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0 L9 4.5 L0 9 Z" fill="#64748b"/></marker></defs><style>text{{font-family:Arial,Helvetica,sans-serif;fill:#1e293b}}.title{{font-size:29px;font-weight:700}}.label{{font-size:21px;font-weight:600}}.body{{font-size:18px;fill:#475569}}.note{{font-size:17px;fill:#64748b}}.arrow{{fill:none;stroke:#64748b;stroke-width:2;marker-end:url(#arrow)}}</style><rect width="1280" height="{height}" fill="#fff"/>'''
        ]
        self.text(40, 44, title, "title")
        self.text(40, 76, description, "body")

    def text(self, x, y, value, kind="body", anchor=None):
        a = f' text-anchor="{anchor}"' if anchor else ""
        self.parts.append(f'<text x="{x}" y="{y}" class="{kind}"{a}>{escape(value)}</text>')

    def box(self, x, y, w, h, title, lines=(), accent=False):
        fill, stroke = ("#eff6ff", "#93c5fd") if accent else ("#f8fafc", "#cbd5e1")
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        self.text(x + 20, y + 32, title, "label")
        for i, line in enumerate(lines):
            self.text(x + 20, y + 62 + i * 27, line)

    def arrow(self, path, label=None, x=0, y=0):
        self.parts.append(f'<path d="{path}" class="arrow"/>')
        if label:
            self.text(x, y, label, "note")

    def save(self, name):
        (ROOT / name).write_text("\n".join(self.parts) + "\n</svg>\n")


s = Diagram(
    "DeepTutor · turn architecture",
    "Current dev: durable application boundary, shared execution engine, two plugin levels.",
    1000,
)
s.box(40, 110, 370, 70, "CLI", ("Typer entry point",))
s.box(455, 110, 370, 70, "WebSocket API", ("/ws commands and event replay",))
s.box(870, 110, 370, 70, "Python SDK", ("DeepTutorApp facade",))
for x in [225, 640, 1055]:
    s.arrow(f"M{x} 180 V205 H640 V228")
s.box(
    350,
    230,
    580,
    100,
    "TurnApplicationService",
    ("Start, cancel, regenerate and replay turns", "Coordinates the per-turn durable runtime"),
    True,
)
s.box(40, 230, 260, 100, "Session store", ("Turn state and events", "SQLite / PocketBase"))
s.box(980, 230, 260, 100, "Runtime coordinator", ("Worker ownership", "Local / Redis"))
s.arrow("M350 280 H300")
s.arrow("M930 280 H980")
s.box(460, 380, 360, 70, "TurnEngine", ("Execute the assembled context",), True)
s.arrow("M640 330 V380")
s.box(460, 500, 360, 80, "ChatOrchestrator", ("Select capability; default: chat",), True)
s.arrow("M640 450 V500")
s.box(
    40,
    495,
    330,
    100,
    "UnifiedContext",
    ("Message, history, resources,", "model policy and turn scope"),
)
s.arrow("M370 540 H460")
s.box(920, 495, 320, 90, "CapabilityRegistry", ("Built-ins and installed plugins",))
s.arrow("M920 540 H820")
s.box(
    40,
    640,
    780,
    165,
    "Level 2 · selected capability",
    (
        "chat · ask_questions · deep_solve · deep_question",
        "deep_research · visualize · math_animator",
        "mastery_path · immersive_reading · video_lesson",
    ),
    True,
)
s.arrow("M640 580 V610 H430 V640")
s.box(
    920,
    640,
    320,
    165,
    "Level 1 · ToolRegistry",
    ("Single-shot tool definitions", "Context / capability gates", "LLM-selected invocations"),
)
s.arrow("M820 720 H920")
s.box(
    40,
    865,
    780,
    100,
    "Per-turn StreamBus",
    ("Capabilities emit typed events and the final result envelope.",),
)
s.arrow("M430 805 V865")
s.box(
    920,
    865,
    320,
    100,
    "Durable consumers",
    ("Runtime persists events;", "adapters subscribe / replay."),
)
s.arrow("M820 910 H920")
s.text(
    40,
    985,
    "Runtime configuration: JSON settings under data/user/settings; workspace resources are scoped.",
    "note",
)
s.save("system-architecture.svg")

c = Diagram(
    "DeepTutor · chat capability loop",
    "The chat loop runs inside the durable turn application and streams typed events.",
    960,
)
c.box(
    360,
    112,
    560,
    85,
    "TurnApplicationService → TurnEngine",
    ("ChatOrchestrator selects the chat capability",),
    True,
)
c.arrow("M640 197 V240")
c.box(
    40,
    240,
    270,
    245,
    "Assembled context",
    (
        "User message and history",
        "Workspace and resources",
        "Memory and persona",
        "Skills and model policy",
        "Mounted tool definitions",
    ),
)
c.box(365, 240, 500, 90, "1  LLM round", ("Generate text and choose tools or finish",), True)
c.arrow("M310 300 H365")
c.box(
    365,
    400,
    500,
    100,
    "2  Invoke selected tools",
    ("ToolRegistry → execute → tool results", "Tools may request user input."),
)
c.arrow("M615 330 V400", "tool calls", 635, 375)
c.box(365, 560, 500, 80, "3  Observe results", ("Append observations to the conversation",))
c.arrow("M615 500 V560")
c.arrow("M365 600 H335 V285 H365", "next round", 225, 535)
c.box(
    365,
    710,
    500,
    150,
    "Finish · capability result",
    (
        "emit_capability_result() emits result",
        "payload.response + metadata",
        "cost_summary / usage_summary when available",
    ),
    True,
)
c.arrow("M865 285 H900 V765 H865", "final answer", 745, 690)
c.box(
    960,
    240,
    280,
    400,
    "Per-turn StreamBus",
    (
        "thinking · content",
        "tool_call · tool_result",
        "observation",
        "wait_for_input",
        "result · done",
        "",
        "Other protocol events:",
        "stages, progress, sources,",
        "session metadata, errors",
    ),
)
c.arrow("M865 445 H960")
c.arrow("M865 805 H925 V610 H960")
c.box(
    960,
    710,
    280,
    150,
    "Persist and replay",
    ("Turn event journal", "Consumer cursor / sequence", "Web UI · CLI · SDK"),
)
c.arrow("M1100 640 V710")
c.text(
    40,
    915,
    "Result data such as response and cost_summary are payload fields, not StreamEventType values.",
    "note",
)
c.text(
    40,
    942,
    "The diagram groups event families; core/stream.py is the authoritative protocol enumeration.",
    "note",
)
c.save("chat-agent-loop.svg")

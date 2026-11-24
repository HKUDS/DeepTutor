// Seed a disposable DeepTutor instance with synthetic, non-personal content
// before capturing the user guide. Run this only against an isolated
// DEEPTUTOR_HOME; it intentionally creates visible product data.
//
//   API_BASE=http://127.0.0.1:18701 node scripts/seed-guide-data.mjs

// The script calls public v1.6.1 APIs instead of copying a developer's local
// database, so published screenshots contain no account names, private chats,
// tokens, or API keys.

const API = process.env.API_BASE ?? "http://127.0.0.1:8001";

async function request(path, init = {}) {
  const response = await fetch(`${API}${path}`, init);
  const body = await response.text();
  let data = body;
  try {
    data = body ? JSON.parse(body) : null;
  } catch {}
  if (!response.ok) {
    throw new Error(`${init.method ?? "GET"} ${path}: ${response.status} ${body}`);
  }
  return data;
}

const json = (method, body) => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

function rows(payload, key) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.[key])) return payload[key];
  if (Array.isArray(payload?.data)) return payload.data;
  return [];
}

async function seedPartner() {
  const existing = rows(await request("/api/v1/partners"), "partners");
  if (existing.some((partner) => partner.id === "sage" || partner.partner_id === "sage")) {
    return;
  }
  await request(
    "/api/v1/partners",
    json("POST", {
      partner_id: "sage",
      name: "Sage",
      description: "A calm study partner for explaining concepts and planning reviews.",
      emoji: "🌿",
      color: "#4F8A6B",
      language: "en",
      enabled_tools: ["web_search", "paper_search", "reason"],
      start: false,
    }),
  );
}

async function seedPartnerChannelStatus() {
  await request(
    "/api/v1/partners/sage",
    json("PATCH", {
      channels: {
        telegram: {
          enabled: true,
          token: "",
          allow_from: ["docs-user"],
        },
      },
    }),
  );
  await request("/api/v1/partners/sage/start", json("POST", {}));
}

async function seedSafeNetworkDisplay() {
  const current = await request("/api/v1/settings/network");
  const settings = current.settings ?? {};
  await request(
    "/api/v1/settings/network",
    json("PUT", {
      backend_port: settings.backend_port ?? 8001,
      frontend_port: settings.frontend_port ?? 3782,
      public_api_base: "http://localhost:8001",
      cors_origins: [],
    }),
  );
}

async function seedCoWriter() {
  const existing = rows(await request("/api/v1/co_writer/documents"), "documents");
  if (existing.some((document) => document.title === "Fourier Transform Study Notes")) {
    return;
  }
  await request(
    "/api/v1/co_writer/documents",
    json("POST", {
      title: "Fourier Transform Study Notes",
      content: [
        "# Fourier Transform Study Notes",
        "",
        "## Core idea",
        "The Fourier transform represents a signal as a weighted combination of frequencies.",
        "",
        "## Review checklist",
        "- Relate time-domain features to the frequency domain.",
        "- Explain amplitude and phase spectra.",
        "- Practice the convolution theorem with one worked example.",
      ].join("\n"),
    }),
  );
}

async function seedNotebook() {
  const existing = rows(await request("/api/v1/notebook/list"), "notebooks");
  let notebook = existing.find((item) => item.name === "Signal Processing Lab");
  if (!notebook) {
    const created = await request(
      "/api/v1/notebook/create",
      json("POST", {
        name: "Signal Processing Lab",
        description: "Key explanations, examples, and follow-up questions.",
        color: "#6366F1",
        icon: "book-open",
      }),
    );
    notebook = created.notebook;
  }
  if (!notebook?.id) throw new Error("Notebook seed did not return an id.");
  const detail = await request(`/api/v1/notebook/${notebook.id}`);
  const records = rows(detail?.notebook ?? detail, "records");
  if (records.length === 0) {
    await request(
      "/api/v1/notebook/add_record",
      json("POST", {
        notebook_ids: [notebook.id],
        record_type: "chat",
        title: "Why frequency-domain views help",
        summary: "A compact comparison of time-domain and frequency-domain reasoning.",
        user_query: "When is the frequency domain more useful than the time domain?",
        output:
          "The frequency domain makes periodic structure, bandwidth, filtering, and convolution easier to inspect. The time domain remains best for timing and transient behavior.",
        metadata: { source: "documentation-demo" },
      }),
    );
    await request(
      "/api/v1/notebook/add_record",
      json("POST", {
        notebook_ids: [notebook.id],
        record_type: "solve",
        title: "Convolution theorem",
        summary: "Convolution in time corresponds to multiplication in frequency.",
        user_query: "State the convolution theorem.",
        output: "If y(t) = x(t) * h(t), then Y(f) = X(f)H(f).",
        metadata: { source: "documentation-demo" },
      }),
    );
  }
}

async function seedQuestionBank() {
  const existing = rows(await request("/api/v1/question-notebook/entries?limit=100"), "entries");
  if (existing.some((entry) => entry.question_id === "docs-fourier-1")) return;
  const workspaces = rows(await request("/api/v1/reading/workspaces"), "workspaces");
  const workspace = workspaces.find(
    (item) => item.title === "Signal Processing Reading List",
  );
  if (!workspace?.workspace_id) {
    throw new Error("Create the demo reading workspace before the question bank.");
  }
  const linked = rows(
    await request(`/api/v1/reading/workspaces/${workspace.workspace_id}/sessions`),
    "sessions",
  );
  let session = linked.find((item) => item.title === "Fourier practice review");
  if (!session) {
    const created = await request(
      `/api/v1/reading/workspaces/${workspace.workspace_id}/sessions`,
      json("POST", {
        title: "Fourier practice review",
        active_material_id: workspace.active_material_id,
      }),
    );
    session = created.session;
  }
  await request(
    "/api/v1/question-notebook/entries/upsert",
    json("POST", {
      session_id: session.session_id,
      turn_id: "docs-demo-turn",
      question_id: "docs-fourier-1",
      question: "Which operation in the frequency domain corresponds to convolution in time?",
      question_type: "multiple_choice",
      options: {
        A: "Addition",
        B: "Multiplication",
        C: "Differentiation",
        D: "Time reversal",
      },
      correct_answer: "B",
      explanation: "The convolution theorem maps time-domain convolution to multiplication.",
      difficulty: "medium",
      user_answer: "B",
      is_correct: true,
    }),
  );
}

async function seedMasteryPath() {
  const existing = rows(await request("/api/v1/learning/topics"), "topics");
  if (existing.some((topic) => topic.name === "Fourier Transform Foundations")) return;
  await request(
    "/api/v1/learning/topics",
    json("POST", {
      name: "Fourier Transform Foundations",
      goal: "Build an intuitive and practical understanding of frequency-domain analysis.",
      description: "A guided route from signals and sinusoids to filtering and convolution.",
      emoji: "〰️",
      modules: [
        {
          name: "Signals and frequency",
          knowledge_points: [
            { name: "Sinusoids, amplitude, and phase", type: "concept" },
            { name: "Time-domain and frequency-domain views", type: "concept" },
          ],
        },
        {
          name: "Transform toolkit",
          knowledge_points: [
            { name: "Fourier transform pairs", type: "memory" },
            { name: "Convolution theorem", type: "procedure" },
          ],
        },
        {
          name: "Apply and explain",
          knowledge_points: [
            { name: "Design a simple frequency filter", type: "design" },
            { name: "Explain spectral leakage", type: "concept" },
          ],
        },
      ],
    }),
  );
}

async function seedReading() {
  const existing = rows(await request("/api/v1/reading/library/materials"), "materials");
  let material = existing.find((item) => item.filename === "fourier-primer.md");
  if (!material) {
    const form = new FormData();
    form.set(
      "file",
      new Blob(
        [
          "# Fourier Transform Primer\n\n",
          "A signal can be described by how it changes over time or by the frequencies it contains.\n\n",
          "## Convolution theorem\n\n",
          "Convolution in the time domain becomes multiplication in the frequency domain. ",
          "This is why many filters are easier to analyze after a Fourier transform.\n\n",
          "## Sampling\n\n",
          "To avoid aliasing, a sampling rate must exceed twice the highest frequency of interest.\n",
        ],
        { type: "text/markdown" },
      ),
      "fourier-primer.md",
    );
    material = await request("/api/v1/reading/materials", { method: "POST", body: form });
  }
  const materialId = material.material_id ?? material.id;
  if (!materialId) throw new Error("Reading material seed did not return an id.");
  const workspaces = rows(await request("/api/v1/reading/workspaces"), "workspaces");
  if (!workspaces.some((workspace) => workspace.title === "Signal Processing Reading List")) {
    await request(
      "/api/v1/reading/workspaces",
      json("POST", {
        title: "Signal Processing Reading List",
        description: "A small collection for reviewing transforms, filtering, and sampling.",
        material_ids: [materialId],
      }),
    );
  }
}

async function seedKnowledgeSpace() {
  const existing = rows(await request("/api/v1/knowledge/list"), "knowledge_bases");
  if (existing.some((kb) => kb.name === "Signal Processing Notes")) return;
  const form = new FormData();
  form.set("name", "Signal Processing Notes");
  form.set("rag_provider", "llamaindex");
  await request("/api/v1/knowledge/create", { method: "POST", body: form });
}

async function seedModelCatalog() {
  const current = await request("/api/v1/settings/catalog");
  const catalog = current.catalog;
  const service = catalog.services.llm;
  if (service.profiles.some((profile) => profile.id === "docs-local-llm")) return;
  service.active_profile_id = "docs-local-llm";
  service.active_model_id = "docs-local-model";
  service.profiles.push({
    id: "docs-local-llm",
    name: "Local study model",
    binding: "llama_cpp",
    base_url: "http://127.0.0.1:8080/v1",
    api_key: "",
    api_version: "",
    extra_headers: {},
    models: [
      {
        id: "docs-local-model",
        name: "Documentation Demo Model",
        model: "demo-instruct",
        context_window: 32768,
      },
    ],
  });
  await request("/api/v1/settings/catalog", json("PUT", { catalog }));
}

async function seedConnectedAgent() {
  const existing = rows(await request("/api/v1/subagents/connections"), "connections");
  if (existing.some((connection) => connection.name === "Sage")) return;
  await request(
    "/api/v1/subagents/connections",
    json("POST", {
      name: "Sage",
      agent_kind: "partner",
      partner_id: "sage",
    }),
  );
}

const tasks = [
  ["partner", seedPartner],
  ["partner channel status", seedPartnerChannelStatus],
  ["co-writer", seedCoWriter],
  ["notebook", seedNotebook],
  ["mastery path", seedMasteryPath],
  ["immersive reading", seedReading],
  ["question bank", seedQuestionBank],
  ["knowledge space", seedKnowledgeSpace],
  ["model catalog", seedModelCatalog],
  ["connected agent", seedConnectedAgent],
  ["safe network display", seedSafeNetworkDisplay],
];

for (const [label, task] of tasks) {
  try {
    await task();
    console.log(`seeded ${label}`);
  } catch (error) {
    console.error(`FAILED ${label}: ${error.message}`);
    process.exitCode = 1;
  }
}

"use client";

import { ChangeEvent, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8001";

type Citation = { book: string; page: number };
type Page = { pdf_page: number; text: string; citation: Citation };

export default function GuruAIPage() {
  const [file, setFile] = useState<File | null>(null);
  const [pages, setPages] = useState<Page[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0];
    if (!selected) return;
    setFile(selected); setError(""); setBusy(true);
    const body = new FormData(); body.append("file", selected);
    try {
      const response = await fetch(`${API}/api/v1/guruai/sources/preview`, { method: "POST", body });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json(); setPages(data.pages ?? []);
    } catch (err) { setError(err instanceof Error ? err.message : "Upload failed"); }
    finally { setBusy(false); }
  }

  function ask() {
    if (!question.trim()) return;
    setAnswer("GuruAI is ready to connect this question to the uploaded syllabus. The next slice will stream the grounded Sinhala answer here.");
  }

  return (
    <main className="guruai-shell min-h-screen overflow-auto p-4 text-white md:p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-8 flex items-center justify-between rounded-3xl border border-white/15 bg-white/10 p-5 shadow-2xl backdrop-blur-xl">
          <div><p className="text-xs uppercase tracking-[0.3em] text-cyan-200">GuruAI · ගුරු AI</p><h1 className="mt-1 text-2xl font-semibold">Learn from your own syllabus</h1></div>
          <span className="rounded-full border border-cyan-200/30 bg-cyan-200/10 px-3 py-1 text-xs text-cyan-100">Local prototype</span>
        </header>
        <section className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="space-y-6">
            <div className="rounded-3xl border border-white/15 bg-white/10 p-6 shadow-xl backdrop-blur-xl">
              <div className="mb-5"><p className="text-sm text-white/60">1 · Add learning material</p><h2 className="mt-1 text-xl font-medium">Upload a syllabus or past paper</h2></div>
              <label className="flex cursor-pointer flex-col items-center rounded-2xl border border-dashed border-cyan-200/40 bg-cyan-200/5 p-8 text-center transition hover:bg-cyan-200/10"><span className="text-3xl">⌁</span><span className="mt-3 text-sm">Choose a PDF</span><span className="mt-1 text-xs text-white/50">Page citations stay attached</span><input className="hidden" type="file" accept="application/pdf" onChange={upload} /></label>
              {file && <p className="mt-3 truncate text-sm text-cyan-100">{file.name} {busy ? "· reading pages…" : `· ${pages.length || ""} preview pages`}</p>}
              {error && <p className="mt-3 text-sm text-rose-200">{error}</p>}
            </div>
            <div className="rounded-3xl border border-white/15 bg-white/10 p-6 shadow-xl backdrop-blur-xl"><p className="text-sm text-white/60">2 · Ask in Sinhala or English</p><textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="ත්‍රිකෝණයක වර්ගඵලය සොයන්නේ කෙසේද?" className="mt-4 min-h-32 w-full resize-none rounded-2xl border border-white/15 bg-black/20 p-4 text-white outline-none placeholder:text-white/35 focus:border-cyan-200/60" /><button onClick={ask} className="mt-4 rounded-full bg-cyan-200 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-white">Explain step by step</button></div>
          </div>
          <div className="rounded-3xl border border-white/15 bg-white/10 p-6 shadow-xl backdrop-blur-xl"><p className="text-sm text-white/60">GuruAI workspace</p><h2 className="mt-1 text-xl font-medium">Your learning canvas</h2>{answer ? <div className="mt-6 rounded-2xl border border-amber-200/30 bg-amber-100/10 p-5"><p className="leading-8 text-white/90">{answer}</p><span className="mt-5 inline-flex rounded-full bg-amber-200/15 px-3 py-1 text-xs text-amber-100">📖 citations will appear here</span></div> : <div className="mt-6 flex min-h-[440px] items-center justify-center rounded-2xl border border-white/10 bg-gradient-to-br from-cyan-200/10 via-transparent to-violet-300/10 text-center text-white/45"><div><div className="mx-auto mb-4 text-6xl opacity-70">◌</div><p>Upload a source, then ask your first question.</p><p className="mt-2 text-sm">Steps, graphs, tables, and citations will live here.</p></div></div>}
            {pages.length > 0 && <div className="mt-5"><p className="mb-3 text-sm text-white/60">Source preview</p><div className="space-y-2">{pages.map((page) => <div key={page.pdf_page} className="rounded-xl border border-white/10 bg-black/15 p-3 text-sm"><span className="text-cyan-100">📖 p.{page.citation.page}</span><span className="ml-3 text-white/55">{page.text.slice(0, 150)}{page.text.length > 150 ? "…" : ""}</span></div>)}</div></div>}
          </div>
        </section>
        <footer className="mt-8 text-xs text-white/40">GuruAI extension · Built on DeepTutor, Apache 2.0 · LiquidGlass-inspired prototype surface</footer>
      </div>
    </main>
  );
}

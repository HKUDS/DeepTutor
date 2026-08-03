(globalThis.TURBOPACK||(globalThis.TURBOPACK=[])).push(["object"==typeof document?document.currentScript:void 0,531278,e=>{"use strict";let t=(0,e.i(475254).default)("loader-circle",[["path",{d:"M21 12a9 9 0 1 1-6.219-8.56",key:"13zald"}]]);e.s(["Loader2",0,t],531278)},107233,e=>{"use strict";let t=(0,e.i(475254).default)("plus",[["path",{d:"M5 12h14",key:"1ays0h"}],["path",{d:"M12 5v14",key:"s699le"}]]);e.s(["Plus",0,t],107233)},178583,e=>{"use strict";let t=(0,e.i(475254).default)("file-text",[["path",{d:"M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",key:"1oefj6"}],["path",{d:"M14 2v5a1 1 0 0 0 1 1h5",key:"wfsgrz"}],["path",{d:"M10 9H8",key:"b1mrlr"}],["path",{d:"M16 13H8",key:"t4e002"}],["path",{d:"M16 17H8",key:"z1uh3a"}]]);e.s(["FileText",0,t],178583)},564123,172136,421872,e=>{"use strict";var t=e.i(554858);let r="/api/v1/co_writer";async function a(e){if(!e.ok){let t=await e.text().catch(()=>"");throw Error(`Request failed (${e.status}): ${t||e.statusText}`)}return e.json()}async function o(){let e=await (0,t.apiFetch)((0,t.apiUrl)(`${r}/documents`),{cache:"no-store"}),o=await a(e);return Array.isArray(o?.documents)?o.documents:[]}async function n(e){return a(await (0,t.apiFetch)((0,t.apiUrl)(`${r}/documents`),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:e?.title??null,content:e?.content??""})}))}async function i(e){return a(await (0,t.apiFetch)((0,t.apiUrl)(`${r}/documents/${encodeURIComponent(e)}`),{cache:"no-store"}))}async function s(e,o){return a(await (0,t.apiFetch)((0,t.apiUrl)(`${r}/documents/${encodeURIComponent(e)}`),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:o.title??null,content:o.content??null})}))}async function d(e){let o=await (0,t.apiFetch)((0,t.apiUrl)(`${r}/documents/${encodeURIComponent(e)}`),{method:"DELETE"}),n=await a(o);return!!n?.deleted}e.s(["createCoWriterDocument",0,n,"deleteCoWriterDocument",0,d,"getCoWriterDocument",0,i,"listCoWriterDocuments",0,o,"updateCoWriterDocument",0,s],564123),e.s(["notifyCoWriterChanged",0,function(){let e=window;e&&e.dispatchEvent(new Event("co-writer:changed"))}],172136);let l=`# DeepTutor Co-Writer

> DeepTutor's built-in writing canvas for notes, reports, tutorials, and AI-assisted drafts.

### Features

- Support Standard Markdown / CommonMark / GFM for everyday writing
- Real-time preview for headings, tables, code, math, flowchart, and sequence diagrams
- AI editing workflows for rewrite, shorten, and expand
- HTML tag decoding for tags like <sub>, <sup>, <abbr>, and <mark>
- A practical starter draft for DeepTutor product docs and learning content

## Headers (Underline)

DeepTutor Learning Note
=============

DeepTutor Study Outline
-------------

### Characters

----

~~Deprecated behavior~~ <s>Legacy formatting path</s>
*Italic* _Italic_
**Emphasis** __Emphasis__
***Emphasis Italic*** ___Emphasis Italic___

Superscript: X<sup>2</sup>, Subscript: O<sub>2</sub>

**Abbreviation(link HTML abbr tag)**

The <abbr title="Large Language Model">LLM</abbr> layer powers DeepTutor while the <abbr title="Retrieval Augmented Generation">RAG</abbr> layer provides grounded knowledge support.

### Blockquotes

> DeepTutor helps students turn questions into structured understanding.
>
> "Learn deeply, write clearly.", [DeepTutor](#deeptutor-co-writer)

### Links

[DeepTutor Co-Writer](#deeptutor-co-writer "co-writer section")

[DeepTutor Learning Note](#deeptutor-learning-note)

[DeepTutor Website](https://deeptutor.info)

[Reference link][deeptutor-doc]

[deeptutor-doc]: #deeptutor-learning-note

### Code Blocks

#### Inline code

\`deeptutor chat --once "Summarize this section"\`

#### Code Blocks (Indented style)

    from deeptutor.runtime.orchestrator import ChatOrchestrator
    orchestrator = ChatOrchestrator()
    print("DeepTutor is ready.")

#### Python

\`\`\`python
from deeptutor.runtime.orchestrator import ChatOrchestrator
from deeptutor.core.context import UnifiedContext


async def run_demo() -> str:
    orchestrator = ChatOrchestrator()
    context = UnifiedContext(
        user_query="Explain Newton's second law",
        capability="chat",
    )
    result = await orchestrator.run(context)
    return result.get("response", "")
\`\`\`

#### JSON config

\`\`\`json
{
  "app_name": "DeepTutor",
  "default_capability": "chat",
  "enabled_tools": ["rag", "web_search", "code_execution", "reason"],
  "ui": {
    "co_writer_template": true
  }
}
\`\`\`

#### HTML code

\`\`\`html
<section class="deeptutor-card">
  <h1>DeepTutor</h1>
  <p>Write, revise, and organize learning content with AI.</p>
</section>
\`\`\`

### Images

![](/logo-ver2.png)

> DeepTutor brand mark used inside the co-writer template.

### Lists

- DeepTutor Chat
- DeepTutor Co-Writer
- DeepTutor Research

1. Draft a concept note
2. Ask AI to refine it
3. Export the polished markdown

### Tables

Feature       | Description
------------- | -------------
Co-Writer     | Draft and refine Markdown content
Chat          | Ask questions and iterate ideas
Research      | Build structured multi-step reports

| Capability    | Primary Use Case                     |
| ------------- | ------------------------------------ |
| \`chat\`       | General tutoring and guidance        |
| \`deep_solve\` | Structured problem solving           |
| \`deep_question\` | Question generation and validation |

### Markdown extras

- [x] Draft a DeepTutor product note
- [x] Add references and structure
- [ ] Polish the final explanation
  - [ ] Check headings
  - [ ] Check citations

### TeX (LaTeX)

$$ E=mc^2 $$

Inline $$E=mc^2$$ appears in physics notes, and Inline $$a^2+b^2=c^2$$ appears in geometry notes.

$$\\sqrt{3x-1}+(1+x)^2$$

$$ \\sin(\\alpha)^{\\theta}=\\sum_{i=0}^{n}(x^i + \\cos(f))$$

### FlowChart

\`\`\`flow
st=>start: Student asks a question
op=>operation: DeepTutor analyzes intent
cond=>condition: Need deep workflow?
chat=>operation: Answer with chat capability
solve=>operation: Route to deep solve
e=>end: Return structured response

st->op->cond
cond(no)->chat
cond(yes)->solve
chat->e
solve->e
\`\`\`

### Sequence Diagram

\`\`\`seq
Student->DeepTutor: Ask for help
DeepTutor->KnowledgeBase: Load context
Note right of DeepTutor: Collect memory\\nand relevant knowledge
DeepTutor-->Student: Return guided response
Student->>DeepTutor: Request rewrite in co-writer
\`\`\`

### End
`;e.s(["CO_WRITER_SAMPLE_TEMPLATE",0,l],421872)},265178,e=>{"use strict";var t=e.i(843476),r=e.i(271645),a=e.i(618566);e.i(785269);var o=e.i(322831),n=e.i(178583),i=e.i(531278),s=e.i(674558),d=e.i(107233),l=e.i(727612),c=e.i(564123),u=e.i(172136),p=e.i(421872);e.s(["default",0,function(){let e=(0,a.useRouter)(),{t:m}=(0,o.useTranslation)(),[h,x]=(0,r.useState)([]),[f,g]=(0,r.useState)(!0),[y,b]=(0,r.useState)(!1),[v,w]=(0,r.useState)(null),[k,C]=(0,r.useState)(null),[T,j]=(0,r.useState)(""),N=(0,r.useCallback)(async()=>{g(!0),j("");try{let e=await (0,c.listCoWriterDocuments)();x(e)}catch(e){j(e instanceof Error?e.message:String(e))}finally{g(!1)}},[]);(0,r.useEffect)(()=>{N()},[N]);let D=(0,r.useCallback)(async t=>{if(!y){b(!0),j("");try{let r=await (0,c.createCoWriterDocument)({content:t?p.CO_WRITER_SAMPLE_TEMPLATE:""});(0,u.notifyCoWriterChanged)(),e.push(`/co-writer/${r.id}`)}catch(e){j(e instanceof Error?e.message:String(e)),b(!1)}}},[y,e]),$=(0,r.useCallback)(async e=>{if(!k){C(e),j("");try{await (0,c.deleteCoWriterDocument)(e),x(t=>t.filter(t=>t.id!==e)),w(null),(0,u.notifyCoWriterChanged)()}catch(e){j(e instanceof Error?e.message:String(e))}finally{C(null)}}},[k]);return(0,t.jsx)("div",{className:"h-full overflow-y-auto bg-[var(--background)]",children:(0,t.jsxs)("div",{className:"mx-auto max-w-5xl px-6 py-8",children:[(0,t.jsxs)("header",{className:"mb-7 flex items-end justify-between gap-4",children:[(0,t.jsxs)("div",{children:[(0,t.jsx)("h1",{className:"text-[19px] font-semibold tracking-tight text-[var(--foreground)]",children:m("Co-Writer")}),(0,t.jsx)("p",{className:"mt-1 text-[12.5px] text-[var(--muted-foreground)]",children:m("Manage your markdown drafts and projects.")})]}),(0,t.jsxs)("div",{className:"flex shrink-0 items-center gap-2",children:[(0,t.jsxs)("button",{type:"button",onClick:()=>D(!0),disabled:y,className:"inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60",children:[(0,t.jsx)(n.FileText,{size:14}),m("From template")]}),(0,t.jsxs)("button",{type:"button",onClick:()=>D(!1),disabled:y,className:"inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-60",children:[y?(0,t.jsx)(i.Loader2,{size:14,className:"animate-spin"}):(0,t.jsx)(d.Plus,{size:14}),m("New draft")]})]})]}),T?(0,t.jsx)("div",{className:"mb-4 rounded-lg border border-rose-300/30 bg-rose-50/40 px-3 py-2 text-[12px] text-rose-700 dark:bg-rose-950/30 dark:text-rose-300",children:T}):null,f?(0,t.jsxs)("div",{className:"flex items-center justify-center gap-2 py-20 text-[12.5px] text-[var(--muted-foreground)]",children:[(0,t.jsx)(i.Loader2,{size:16,className:"animate-spin"}),m("Loading drafts…")]}):0===h.length?(0,t.jsxs)("div",{className:"flex min-h-[360px] flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border)] px-8 text-center",children:[(0,t.jsx)(s.PenLine,{size:30,strokeWidth:1.5,className:"mb-3 text-[var(--muted-foreground)]"}),(0,t.jsx)("p",{className:"text-[14px] font-medium text-[var(--foreground)]",children:m("No drafts yet")}),(0,t.jsx)("p",{className:"mt-1.5 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]",children:m("Start a new markdown draft to begin writing.")}),(0,t.jsxs)("div",{className:"mt-4 flex items-center gap-2",children:[(0,t.jsxs)("button",{type:"button",onClick:()=>D(!1),disabled:y,className:"inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-60",children:[y?(0,t.jsx)(i.Loader2,{size:14,className:"animate-spin"}):(0,t.jsx)(d.Plus,{size:14}),m("New draft")]}),(0,t.jsxs)("button",{type:"button",onClick:()=>D(!0),disabled:y,className:"inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60",children:[(0,t.jsx)(n.FileText,{size:14}),m("Start from template")]})]})]}):(0,t.jsx)("div",{className:"grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3",children:h.map(r=>{let a=v===r.id,o=k===r.id;return(0,t.jsxs)("div",{role:"button",tabIndex:0,onClick:()=>e.push(`/co-writer/${r.id}`),onKeyDown:t=>{("Enter"===t.key||" "===t.key)&&(t.preventDefault(),e.push(`/co-writer/${r.id}`))},className:"group relative flex h-44 cursor-pointer flex-col rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)]",children:[(0,t.jsxs)("div",{className:"flex items-start justify-between gap-2",children:[(0,t.jsxs)("div",{className:"flex min-w-0 items-start gap-2",children:[(0,t.jsx)(n.FileText,{size:15,className:"mt-0.5 shrink-0 text-[var(--muted-foreground)]"}),(0,t.jsxs)("div",{className:"min-w-0",children:[(0,t.jsx)("div",{className:"truncate text-[14px] font-medium text-[var(--foreground)]",title:r.title||m("Untitled draft"),children:r.title||m("Untitled draft")}),(0,t.jsxs)("div",{className:"mt-0.5 text-[11px] text-[var(--muted-foreground)]/70",children:[m("Updated")," ",function(e){if(!e||Number.isNaN(e))return"";let t=Date.now()/1e3-e;if(t<60)return"1m";let r=Math.floor(t/60);if(r<60)return`${r}m`;let a=Math.floor(r/60);if(a<24)return`${a}h`;let o=Math.floor(a/24);if(o<30)return`${o}d`;let n=Math.floor(o/30);return n<12?`${n}mo`:`${Math.floor(n/12)}y`}(r.updated_at)," ",m("ago")]})]})]}),(0,t.jsx)("button",{type:"button",onClick:e=>{e.stopPropagation(),a?$(r.id):w(r.id)},disabled:o,title:a?m("Click again to confirm"):m("Delete draft"),className:`shrink-0 rounded-md p-1 transition-colors disabled:opacity-50 ${a?"bg-rose-500/15 text-rose-600 dark:text-rose-400":"text-[var(--muted-foreground)]/60 opacity-0 hover:bg-rose-500/10 hover:text-rose-600 group-hover:opacity-100 dark:hover:text-rose-400"}`,children:o?(0,t.jsx)(i.Loader2,{size:13,className:"animate-spin"}):(0,t.jsx)(l.Trash2,{size:13})})]}),(0,t.jsx)("p",{className:"mt-2.5 line-clamp-4 flex-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]",children:r.preview||m("Empty draft")})]},r.id)})})]})})}])}]);
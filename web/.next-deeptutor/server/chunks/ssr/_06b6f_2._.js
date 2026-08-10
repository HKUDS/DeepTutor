module.exports=[596221,a=>{"use strict";let b=(0,a.i(883706).default)("loader-circle",[["path",{d:"M21 12a9 9 0 1 1-6.219-8.56",key:"13zald"}]]);a.s(["Loader2",0,b],596221)},915618,a=>{"use strict";let b=(0,a.i(883706).default)("plus",[["path",{d:"M5 12h14",key:"1ays0h"}],["path",{d:"M12 5v14",key:"s699le"}]]);a.s(["Plus",0,b],915618)},104720,a=>{"use strict";let b=(0,a.i(883706).default)("file-text",[["path",{d:"M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",key:"1oefj6"}],["path",{d:"M14 2v5a1 1 0 0 0 1 1h5",key:"wfsgrz"}],["path",{d:"M10 9H8",key:"b1mrlr"}],["path",{d:"M16 13H8",key:"t4e002"}],["path",{d:"M16 17H8",key:"z1uh3a"}]]);a.s(["FileText",0,b],104720)},670024,680224,172132,a=>{"use strict";var b=a.i(353250);let c="/api/v1/co_writer";async function d(a){if(!a.ok){let b=await a.text().catch(()=>"");throw Error(`Request failed (${a.status}): ${b||a.statusText}`)}return a.json()}async function e(){let a=await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents`),{cache:"no-store"}),e=await d(a);return Array.isArray(e?.documents)?e.documents:[]}async function f(a){return d(await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents`),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:a?.title??null,content:a?.content??""})}))}async function g(a){return d(await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents/${encodeURIComponent(a)}`),{cache:"no-store"}))}async function h(a,e){return d(await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents/${encodeURIComponent(a)}`),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:e.title??null,content:e.content??null})}))}async function i(a){let e=await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents/${encodeURIComponent(a)}`),{method:"DELETE"}),f=await d(e);return!!f?.deleted}a.s(["createCoWriterDocument",0,f,"deleteCoWriterDocument",0,i,"getCoWriterDocument",0,g,"listCoWriterDocuments",0,e,"updateCoWriterDocument",0,h],670024),a.s(["notifyCoWriterChanged",0,function(){}],680224);let j=`# DeepTutor Co-Writer

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
`;a.s(["CO_WRITER_SAMPLE_TEMPLATE",0,j],172132)},825102,a=>{"use strict";var b=a.i(187924),c=a.i(572131),d=a.i(50944);a.i(802407);var e=a.i(778134),f=a.i(104720),g=a.i(596221),h=a.i(78823),i=a.i(915618),j=a.i(781560),k=a.i(670024),l=a.i(680224),m=a.i(172132);a.s(["default",0,function(){let a=(0,d.useRouter)(),{t:n}=(0,e.useTranslation)(),[o,p]=(0,c.useState)([]),[q,r]=(0,c.useState)(!0),[s,t]=(0,c.useState)(!1),[u,v]=(0,c.useState)(null),[w,x]=(0,c.useState)(null),[y,z]=(0,c.useState)(""),A=(0,c.useCallback)(async()=>{r(!0),z("");try{let a=await (0,k.listCoWriterDocuments)();p(a)}catch(a){z(a instanceof Error?a.message:String(a))}finally{r(!1)}},[]);(0,c.useEffect)(()=>{A()},[A]);let B=(0,c.useCallback)(async b=>{if(!s){t(!0),z("");try{let c=await (0,k.createCoWriterDocument)({content:b?m.CO_WRITER_SAMPLE_TEMPLATE:""});(0,l.notifyCoWriterChanged)(),a.push(`/co-writer/${c.id}`)}catch(a){z(a instanceof Error?a.message:String(a)),t(!1)}}},[s,a]),C=(0,c.useCallback)(async a=>{if(!w){x(a),z("");try{await (0,k.deleteCoWriterDocument)(a),p(b=>b.filter(b=>b.id!==a)),v(null),(0,l.notifyCoWriterChanged)()}catch(a){z(a instanceof Error?a.message:String(a))}finally{x(null)}}},[w]);return(0,b.jsx)("div",{className:"h-full overflow-y-auto bg-[var(--background)]",children:(0,b.jsxs)("div",{className:"mx-auto max-w-5xl px-6 py-8",children:[(0,b.jsxs)("header",{className:"mb-7 flex items-end justify-between gap-4",children:[(0,b.jsxs)("div",{children:[(0,b.jsx)("h1",{className:"text-[19px] font-semibold tracking-tight text-[var(--foreground)]",children:n("Co-Writer")}),(0,b.jsx)("p",{className:"mt-1 text-[12.5px] text-[var(--muted-foreground)]",children:n("Manage your markdown drafts and projects.")})]}),(0,b.jsxs)("div",{className:"flex shrink-0 items-center gap-2",children:[(0,b.jsxs)("button",{type:"button",onClick:()=>B(!0),disabled:s,className:"inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60",children:[(0,b.jsx)(f.FileText,{size:14}),n("From template")]}),(0,b.jsxs)("button",{type:"button",onClick:()=>B(!1),disabled:s,className:"inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-60",children:[s?(0,b.jsx)(g.Loader2,{size:14,className:"animate-spin"}):(0,b.jsx)(i.Plus,{size:14}),n("New draft")]})]})]}),y?(0,b.jsx)("div",{className:"mb-4 rounded-lg border border-rose-300/30 bg-rose-50/40 px-3 py-2 text-[12px] text-rose-700 dark:bg-rose-950/30 dark:text-rose-300",children:y}):null,q?(0,b.jsxs)("div",{className:"flex items-center justify-center gap-2 py-20 text-[12.5px] text-[var(--muted-foreground)]",children:[(0,b.jsx)(g.Loader2,{size:16,className:"animate-spin"}),n("Loading drafts…")]}):0===o.length?(0,b.jsxs)("div",{className:"flex min-h-[360px] flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border)] px-8 text-center",children:[(0,b.jsx)(h.PenLine,{size:30,strokeWidth:1.5,className:"mb-3 text-[var(--muted-foreground)]"}),(0,b.jsx)("p",{className:"text-[14px] font-medium text-[var(--foreground)]",children:n("No drafts yet")}),(0,b.jsx)("p",{className:"mt-1.5 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]",children:n("Start a new markdown draft to begin writing.")}),(0,b.jsxs)("div",{className:"mt-4 flex items-center gap-2",children:[(0,b.jsxs)("button",{type:"button",onClick:()=>B(!1),disabled:s,className:"inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-60",children:[s?(0,b.jsx)(g.Loader2,{size:14,className:"animate-spin"}):(0,b.jsx)(i.Plus,{size:14}),n("New draft")]}),(0,b.jsxs)("button",{type:"button",onClick:()=>B(!0),disabled:s,className:"inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60",children:[(0,b.jsx)(f.FileText,{size:14}),n("Start from template")]})]})]}):(0,b.jsx)("div",{className:"grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3",children:o.map(c=>{let d=u===c.id,e=w===c.id;return(0,b.jsxs)("div",{role:"button",tabIndex:0,onClick:()=>a.push(`/co-writer/${c.id}`),onKeyDown:b=>{("Enter"===b.key||" "===b.key)&&(b.preventDefault(),a.push(`/co-writer/${c.id}`))},className:"group relative flex h-44 cursor-pointer flex-col rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)]",children:[(0,b.jsxs)("div",{className:"flex items-start justify-between gap-2",children:[(0,b.jsxs)("div",{className:"flex min-w-0 items-start gap-2",children:[(0,b.jsx)(f.FileText,{size:15,className:"mt-0.5 shrink-0 text-[var(--muted-foreground)]"}),(0,b.jsxs)("div",{className:"min-w-0",children:[(0,b.jsx)("div",{className:"truncate text-[14px] font-medium text-[var(--foreground)]",title:c.title||n("Untitled draft"),children:c.title||n("Untitled draft")}),(0,b.jsxs)("div",{className:"mt-0.5 text-[11px] text-[var(--muted-foreground)]/70",children:[n("Updated")," ",function(a){if(!a||Number.isNaN(a))return"";let b=Date.now()/1e3-a;if(b<60)return"1m";let c=Math.floor(b/60);if(c<60)return`${c}m`;let d=Math.floor(c/60);if(d<24)return`${d}h`;let e=Math.floor(d/24);if(e<30)return`${e}d`;let f=Math.floor(e/30);return f<12?`${f}mo`:`${Math.floor(f/12)}y`}(c.updated_at)," ",n("ago")]})]})]}),(0,b.jsx)("button",{type:"button",onClick:a=>{a.stopPropagation(),d?C(c.id):v(c.id)},disabled:e,title:d?n("Click again to confirm"):n("Delete draft"),className:`shrink-0 rounded-md p-1 transition-colors disabled:opacity-50 ${d?"bg-rose-500/15 text-rose-600 dark:text-rose-400":"text-[var(--muted-foreground)]/60 opacity-0 hover:bg-rose-500/10 hover:text-rose-600 group-hover:opacity-100 dark:hover:text-rose-400"}`,children:e?(0,b.jsx)(g.Loader2,{size:13,className:"animate-spin"}):(0,b.jsx)(j.Trash2,{size:13})})]}),(0,b.jsx)("p",{className:"mt-2.5 line-clamp-4 flex-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]",children:c.preview||n("Empty draft")})]},c.id)})})]})})}])}];

//# sourceMappingURL=_06b6f_2._.js.map
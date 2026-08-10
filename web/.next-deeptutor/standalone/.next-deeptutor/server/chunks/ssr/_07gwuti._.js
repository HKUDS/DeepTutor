module.exports=[596221,a=>{"use strict";let b=(0,a.i(883706).default)("loader-circle",[["path",{d:"M21 12a9 9 0 1 1-6.219-8.56",key:"13zald"}]]);a.s(["Loader2",0,b],596221)},284505,a=>{"use strict";let b=(0,a.i(883706).default)("download",[["path",{d:"M12 15V3",key:"m9g1x1"}],["path",{d:"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4",key:"ih7n3h"}],["path",{d:"m7 10 5 5 5-5",key:"brsn70"}]]);a.s(["Download",0,b],284505)},859749,a=>{"use strict";var b=a.i(353250);async function c(){let a=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/notebook/list"),{cache:"no-store"});if(!a.ok)throw Error(`Request failed: ${a.status}`);return(await a.json()).notebooks??[]}async function d(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/notebook/${a}`),{cache:"no-store"});if(!c.ok)throw Error(`Request failed: ${c.status}`);return await c.json()}async function e(a){let c=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/notebook/create"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:a.name,description:a.description??"",color:a.color??"#6366F1",icon:a.icon??"book"})});if(!c.ok)throw Error(`Request failed: ${c.status}`);return(await c.json()).notebook}async function f(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/notebook/${a}`),{method:"DELETE"});if(!c.ok)throw Error(`Request failed: ${c.status}`)}async function g(a){if(!a.ok)throw Error(`Request failed: ${a.status}`);return a.json()}async function h(a={}){let c=new URLSearchParams;void 0!==a.category_id&&c.set("category_id",String(a.category_id)),void 0!==a.bookmarked&&c.set("bookmarked",String(a.bookmarked)),void 0!==a.is_correct&&c.set("is_correct",String(a.is_correct)),void 0!==a.limit&&c.set("limit",String(a.limit)),void 0!==a.offset&&c.set("offset",String(a.offset));let d=c.toString();return g(await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/question-notebook/entries${d?`?${d}`:""}`),{cache:"no-store"}))}async function i(a,c){let d=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/question-notebook/entries/${a}`),{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(c)});await g(d)}async function j(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/question-notebook/entries/${a}`),{method:"DELETE"});await g(c)}async function k(a,c){let d=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/question-notebook/entries/${a}/categories/${c}`),{method:"DELETE"});await g(d)}async function l(){return g(await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/question-notebook/categories"),{cache:"no-store"}))}async function m(a){return g(await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/question-notebook/categories"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:a})}))}async function n(a,c){let d=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/question-notebook/categories/${a}`),{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:c})});await g(d)}async function o(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/question-notebook/categories/${a}`),{method:"DELETE"});await g(c)}a.s(["createCategory",0,m,"createNotebook",0,e,"deleteCategory",0,o,"deleteNotebook",0,f,"deleteNotebookEntry",0,j,"getNotebook",0,d,"listCategories",0,l,"listNotebookEntries",0,h,"listNotebooks",0,c,"removeEntryFromCategory",0,k,"renameCategory",0,n,"updateNotebookEntry",0,i])},367295,a=>{"use strict";let b=(0,a.i(883706).default)("wand-sparkles",[["path",{d:"m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72",key:"ul74o6"}],["path",{d:"m14 7 3 3",key:"1r5n42"}],["path",{d:"M5 6v4",key:"ilb8ba"}],["path",{d:"M19 14v4",key:"blhpug"}],["path",{d:"M10 2v2",key:"7u0qdc"}],["path",{d:"M7 8H3",key:"zfb6yr"}],["path",{d:"M21 16h-4",key:"1cnmox"}],["path",{d:"M11 3H9",key:"1obp7u"}]]);a.s(["default",0,b])},732860,a=>{"use strict";let b=(0,a.i(883706).default)("arrow-right",[["path",{d:"M5 12h14",key:"1ays0h"}],["path",{d:"m12 5 7 7-7 7",key:"xquz4c"}]]);a.s(["ArrowRight",0,b],732860)},922520,a=>{"use strict";let b=(0,a.i(883706).default)("arrow-up-right",[["path",{d:"M7 7h10v10",key:"1tivn9"}],["path",{d:"M7 17 17 7",key:"1vkiza"}]]);a.s(["ArrowUpRight",0,b],922520)},50522,a=>{"use strict";let b=(0,a.i(883706).default)("chevron-right",[["path",{d:"m9 18 6-6-6-6",key:"mthhwq"}]]);a.s(["ChevronRight",0,b],50522)},856972,a=>{"use strict";let b=(0,a.i(883706).default)("notebook-pen",[["path",{d:"M13.4 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7.4",key:"re6nr2"}],["path",{d:"M2 6h4",key:"aawbzj"}],["path",{d:"M2 10h4",key:"l0bgd4"}],["path",{d:"M2 14h4",key:"1gsvsf"}],["path",{d:"M2 18h4",key:"1bu2t1"}],["path",{d:"M21.378 5.626a1 1 0 1 0-3.004-3.004l-5.01 5.012a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506z",key:"pqwjuv"}]]);a.s(["NotebookPen",0,b],856972)},132245,(a,b,c)=>{"use strict";Object.defineProperty(c,"__esModule",{value:!0}),Object.defineProperty(c,"BailoutToCSR",{enumerable:!0,get:function(){return e}});let d=a.r(441997);function e({reason:a,children:b}){throw Object.defineProperty(new d.BailoutToCSRError(a),"__NEXT_ERROR_CODE",{value:"E394",enumerable:!1,configurable:!0})}},307773,(a,b,c)=>{"use strict";function d(a){return a.split("/").map(a=>encodeURIComponent(a)).join("/")}Object.defineProperty(c,"__esModule",{value:!0}),Object.defineProperty(c,"encodeURIPath",{enumerable:!0,get:function(){return d}})},297458,(a,b,c)=>{"use strict";Object.defineProperty(c,"__esModule",{value:!0}),Object.defineProperty(c,"PreloadChunks",{enumerable:!0,get:function(){return i}});let d=a.r(187924),e=a.r(935112),f=a.r(556704),g=a.r(307773),h=a.r(68063);function i({moduleIds:a}){let b=f.workAsyncStorage.getStore();if(void 0===b)return null;let c=[];if(b.reactLoadableManifest&&a){let d=b.reactLoadableManifest;for(let b of a){if(!d[b])continue;let a=d[b].files;c.push(...a)}}if(0===c.length)return null;let j=(0,h.getAssetTokenQuery)();return(0,d.jsx)(d.Fragment,{children:c.map(a=>{let c=`${b.assetPrefix}/_next/${(0,g.encodeURIPath)(a)}${j}`;return a.endsWith(".css")?(0,d.jsx)("link",{precedence:"dynamic",href:c,rel:"stylesheet",as:"style",nonce:b.nonce},a):((0,e.preload)(c,{as:"script",fetchPriority:"low",nonce:b.nonce}),null)})})}},969853,(a,b,c)=>{"use strict";Object.defineProperty(c,"__esModule",{value:!0}),Object.defineProperty(c,"default",{enumerable:!0,get:function(){return j}});let d=a.r(187924),e=a.r(572131),f=a.r(132245),g=a.r(297458);function h(a){return{default:a&&"default"in a?a.default:a}}let i={loader:()=>Promise.resolve(h(()=>null)),loading:null,ssr:!0},j=function(a){let b={...i,...a},c=(0,e.lazy)(()=>b.loader().then(h)),j=b.loading;function k(a){let h=j?(0,d.jsx)(j,{isLoading:!0,pastDelay:!0,error:null}):null,i=!b.ssr||!!b.loading,k=i?e.Suspense:e.Fragment,l=b.ssr?(0,d.jsxs)(d.Fragment,{children:[(0,d.jsx)(g.PreloadChunks,{moduleIds:b.modules}),(0,d.jsx)(c,{...a})]}):(0,d.jsx)(f.BailoutToCSR,{reason:"next/dynamic",children:(0,d.jsx)(c,{...a})});return(0,d.jsx)(k,{...i?{fallback:h}:{},children:l})}return k.displayName="LoadableComponent",k}},819721,(a,b,c)=>{"use strict";Object.defineProperty(c,"__esModule",{value:!0}),Object.defineProperty(c,"default",{enumerable:!0,get:function(){return e}});let d=a.r(833354)._(a.r(969853));function e(a,b){let c={};"function"==typeof a&&(c.loader=a);let e={...c,...b};return(0,d.default)({...e,modules:e.loadableGenerated?.modules})}("function"==typeof c.default||"object"==typeof c.default&&null!==c.default)&&void 0===c.default.__esModule&&(Object.defineProperty(c.default,"__esModule",{value:!0}),Object.assign(c.default,c),b.exports=c.default)},563588,a=>{"use strict";let b=(0,a.i(883706).default)("message-square",[["path",{d:"M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z",key:"18887p"}]]);a.s(["MessageSquare",0,b],563588)},106807,a=>{"use strict";let b=(0,a.i(883706).default)("workflow",[["rect",{width:"8",height:"8",x:"3",y:"3",rx:"2",key:"by2w9f"}],["path",{d:"M7 11v4a2 2 0 0 0 2 2h4",key:"xkn7yn"}],["rect",{width:"8",height:"8",x:"13",y:"13",rx:"2",key:"1cgmvn"}]]);a.s(["Workflow",0,b],106807)},701110,a=>{"use strict";let b=(0,a.i(883706).default)("undo-2",[["path",{d:"M9 14 4 9l5-5",key:"102s5s"}],["path",{d:"M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11",key:"f3b9sd"}]]);a.s(["Undo2",0,b],701110)},670024,680224,172132,a=>{"use strict";var b=a.i(353250);let c="/api/v1/co_writer";async function d(a){if(!a.ok){let b=await a.text().catch(()=>"");throw Error(`Request failed (${a.status}): ${b||a.statusText}`)}return a.json()}async function e(){let a=await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents`),{cache:"no-store"}),e=await d(a);return Array.isArray(e?.documents)?e.documents:[]}async function f(a){return d(await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents`),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:a?.title??null,content:a?.content??""})}))}async function g(a){return d(await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents/${encodeURIComponent(a)}`),{cache:"no-store"}))}async function h(a,e){return d(await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents/${encodeURIComponent(a)}`),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:e.title??null,content:e.content??null})}))}async function i(a){let e=await (0,b.apiFetch)((0,b.apiUrl)(`${c}/documents/${encodeURIComponent(a)}`),{method:"DELETE"}),f=await d(e);return!!f?.deleted}a.s(["createCoWriterDocument",0,f,"deleteCoWriterDocument",0,i,"getCoWriterDocument",0,g,"listCoWriterDocuments",0,e,"updateCoWriterDocument",0,h],670024),a.s(["notifyCoWriterChanged",0,function(){}],680224);let j=`# DeepTutor Co-Writer

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
`;a.s(["CO_WRITER_SAMPLE_TEMPLATE",0,j],172132)},838632,a=>{"use strict";let b=(0,a.i(883706).default)("image",[["rect",{width:"18",height:"18",x:"3",y:"3",rx:"2",ry:"2",key:"1m3agn"}],["circle",{cx:"9",cy:"9",r:"2",key:"af1f0g"}],["path",{d:"m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21",key:"1xmnt7"}]]);a.s(["Image",0,b],838632)},613749,a=>{"use strict";let b=(0,a.i(883706).default)("chevron-left",[["path",{d:"m15 18-6-6 6-6",key:"1wnfg3"}]]);a.s(["ChevronLeft",0,b],613749)},104720,a=>{"use strict";let b=(0,a.i(883706).default)("file-text",[["path",{d:"M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",key:"1oefj6"}],["path",{d:"M14 2v5a1 1 0 0 0 1 1h5",key:"wfsgrz"}],["path",{d:"M10 9H8",key:"b1mrlr"}],["path",{d:"M16 13H8",key:"t4e002"}],["path",{d:"M16 17H8",key:"z1uh3a"}]]);a.s(["FileText",0,b],104720)},82098,a=>{"use strict";let b=(0,a.i(883706).default)("braces",[["path",{d:"M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1",key:"ezmyqa"}],["path",{d:"M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1",key:"e1hn23"}]]);a.s(["Braces",0,b],82098)},73841,a=>{"use strict";var b=a.i(353250),c=a.i(310496);let d="knowledge:",e=[".bmp",".gif",".jpeg",".jpg",".png",".tif",".tiff",".webp"],f=["image/bmp","image/gif","image/jpeg","image/png","image/tiff","image/webp"];async function g(a){return(0,c.withClientCache)(`${d}list`,async()=>{let a=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/list"),{cache:"no-store"}),c=await a.json();return Array.isArray(c)?c:Array.isArray(c?.knowledge_bases)?c.knowledge_bases:[]},{force:a?.force})}async function h(a){return(0,c.withClientCache)(`${d}providers`,async()=>{let a=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/rag-providers"),{cache:"no-store"}),c=await a.json();return Array.isArray(c?.providers)?c.providers:[]},{force:a?.force})}async function i(a){return(0,c.withClientCache)(`${d}upload-policy`,async()=>{var a;let c,d,g=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/supported-file-types"),{cache:"no-store"});return a=await g.json(),c=Array.from(new Set([...Array.isArray(a?.extensions)?a.extensions:[],...e])).sort(),d=Array.from(new Set([..."string"==typeof a?.accept?a.accept.split(",").map(a=>a.trim()).filter(Boolean):[],...c,...f])).join(","),{extensions:c,accept:d,max_file_size_bytes:"number"==typeof a?.max_file_size_bytes?a.max_file_size_bytes:0xc800000}},{force:a?.force})}function j(){(0,c.invalidateClientCache)(d)}let k="/api/v1/knowledge/rag-pipelines/pageindex/config";async function l(a){return(0,c.withClientCache)(`${d}pageindex-config`,async()=>{let a=await (0,b.apiFetch)((0,b.apiUrl)(k),{cache:"no-store"});if(!a.ok)throw Error(await z(a,"Failed to read PageIndex config"));return await a.json()},{force:a?.force,ttlMs:15e3})}async function m(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(k),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(a)});if(!c.ok)throw Error(await z(c,"Failed to update PageIndex config"));return j(),await c.json()}let n="/api/v1/knowledge/rag-pipelines/llamaindex/config";async function o(a){return(0,c.withClientCache)(`${d}llamaindex-config`,async()=>{let a=await (0,b.apiFetch)((0,b.apiUrl)(n),{cache:"no-store"});if(!a.ok)throw Error(await z(a,"Failed to read LlamaIndex config"));return await a.json()},{force:a?.force,ttlMs:15e3})}async function p(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(n),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(a)});if(!c.ok)throw Error(await z(c,"Failed to update LlamaIndex config"));return j(),await c.json()}async function q(a,e,f){return(0,c.withClientCache)(`${d}${e}`,async()=>{let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/rag-pipelines/${a}/config`),{cache:"no-store"});if(!c.ok)throw Error(await z(c,`Failed to read ${a} config`));return await c.json()},{force:f?.force,ttlMs:15e3})}async function r(a,c){let d=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/rag-pipelines/${a}/config`),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(c)});if(!d.ok)throw Error(await z(d,`Failed to update ${a} config`));return j(),await d.json()}async function s(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/rag-pipelines/${a}/preflight`),{cache:"no-store"});if(!c.ok)throw Error(await z(c,"Failed to check environment"));return await c.json()}async function t(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/rag-pipelines/model-options?kinds=${encodeURIComponent(a.join(","))}`),{cache:"no-store"});if(!c.ok)throw Error(await z(c,"Failed to read model options"));return await c.json()}async function u(a,c,d){let e=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/rag-pipelines/active-model"),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:a,profile_id:c,model_id:d})});if(!e.ok)throw Error(await z(e,"Failed to switch model"));return j(),await e.json()}async function v(a,c){let d=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/rag-providers/${encodeURIComponent(a)}/mode`),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({mode:c})});if(!d.ok)throw Error(await z(d,"Failed to update retrieval mode"));return j(),await d.json()}function w(a,b,c){return 404===b&&"not found"===a.trim().toLowerCase()?`${c} endpoint not found (404). The web UI may be newer than the backend API. If using Docker, pull and recreate the container, then retry.`:a}async function x(a,e){return(0,c.withClientCache)(`${d}files:${a}`,async()=>{let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/${encodeURIComponent(a)}/files`),{cache:"no-store"});if(!c.ok)throw Error(w(await z(c,`Failed to list files (${c.status})`),c.status,"Knowledge file listing"));let d=await c.json();return Array.isArray(d?.files)?d.files:[]},{force:e?.force,ttlMs:15e3})}function y(a,b){return`/api/v1/knowledge/${encodeURIComponent(a)}/files/${b.split("/").map(encodeURIComponent).join("/")}`}async function z(a,b){try{let b=await a.json();if(b?.detail)return String(b.detail)}catch{}return b}function A(a,b){b.forEach(b=>{a.append("files",b),a.append("rel_paths",b.webkitRelativePath||"")})}async function B(a){let c=new FormData;c.append("name",a.name),c.append("rag_provider",a.provider),A(c,a.files);let d=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/create"),{method:"POST",body:c});if(!d.ok)throw Error(await z(d,"Failed to create knowledge base"));return j(),await d.json()}async function C(a){let c=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/connect-obsidian"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:a.name,vault_path:a.vaultPath})});if(!c.ok)throw Error(await z(c,"Failed to connect Obsidian vault"));return j(),await c.json()}async function D(a){let c=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/probe-folder"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({folder_path:a.folderPath,rag_provider:a.provider})});if(!c.ok)throw Error(await z(c,"Failed to inspect folder"));return await c.json()}async function E(a){let c=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/connect-folder"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:a.name,folder_path:a.folderPath,rag_provider:a.provider})});if(!c.ok)throw Error(await z(c,"Failed to link folder"));return j(),await c.json()}async function F(a){let c=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/probe-lightrag-server"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({server_url:a.serverUrl,api_key:a.apiKey??""})});if(!c.ok)throw Error(await z(c,"Failed to reach LightRAG server"));return await c.json()}async function G(a){let c=await (0,b.apiFetch)((0,b.apiUrl)("/api/v1/knowledge/connect-lightrag-server"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:a.name,server_url:a.serverUrl,api_key:a.apiKey??"",search_mode:a.mode??""})});if(!c.ok)throw Error(await z(c,"Failed to connect LightRAG server"));return j(),await c.json()}async function H(a,c,d){let e=new FormData;A(e,c),d?.provider&&e.append("rag_provider",d.provider);let f=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/${encodeURIComponent(a)}/upload`),{method:"POST",body:e});if(!f.ok)throw Error(await z(f,"Failed to upload files"));return j(),await f.json()}async function I(a,c){let d=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/${encodeURIComponent(a)}/folders`),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:c})});if(!d.ok)throw Error(await z(d,"Failed to create folder"));j()}async function J(a,c,d){let e=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/${encodeURIComponent(a)}/files/move`),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source:c,dest_folder:d})});if(!e.ok)throw Error(await z(e,"Failed to move file"));j()}async function K(a,c){let d=await (0,b.apiFetch)((0,b.apiUrl)(y(a,c)),{method:"DELETE"});if(!d.ok)throw Error(await z(d,"Failed to delete file"));return j(),await d.json()}async function L(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/default/${encodeURIComponent(a)}`),{method:"PUT"});if(!c.ok)throw Error(await z(c,"Failed to set default"));j()}async function M(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/${encodeURIComponent(a)}/reindex`),{method:"POST"});if(!c.ok)throw Error(w(await z(c,`Re-index failed (${c.status})`),c.status,"Knowledge re-index"));return j(),await c.json()}async function N(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/${encodeURIComponent(a)}/retry`),{method:"POST"});if(!c.ok)throw Error(w(await z(c,`Retry failed (${c.status})`),c.status,"Knowledge retry"));return j(),await c.json()}async function O(a){let c=await (0,b.apiFetch)((0,b.apiUrl)(`/api/v1/knowledge/${encodeURIComponent(a)}`),{method:"DELETE"});if(!c.ok)throw Error(await z(c,`Delete failed (${c.status})`));j()}a.s(["connectLightRagServer",0,G,"connectLinkedFolder",0,E,"connectObsidianVault",0,C,"createKbFolder",0,I,"createKnowledgeBase",0,B,"deleteKbFile",0,K,"deleteKnowledgeBase",0,O,"getEngineModelOptions",0,t,"getEnginePreflight",0,s,"getGraphRagConfig",0,a=>q("graphrag","graphrag-config",a),"getKnowledgeUploadPolicy",0,i,"getLightRagConfig",0,a=>q("lightrag","lightrag-config",a),"getLlamaIndexConfig",0,o,"getPageIndexConfig",0,l,"invalidateKnowledgeCaches",0,j,"knowledgeBaseFilePath",0,y,"knowledgeBaseFilePreviewTextPath",0,function(a,b){return`/api/v1/knowledge/${encodeURIComponent(a)}/file-preview-text/${b.split("/").map(encodeURIComponent).join("/")}`},"listKnowledgeBaseFiles",0,x,"listKnowledgeBases",0,g,"listRagProviders",0,h,"moveKbFile",0,J,"probeLightRagServer",0,F,"probeLinkedFolder",0,D,"reindexKnowledgeBase",0,M,"retryKnowledgeBase",0,N,"setDefaultKnowledgeBase",0,L,"setEngineActiveModel",0,u,"updateGraphRagConfig",0,a=>r("graphrag",a),"updateLightRagConfig",0,a=>r("lightrag",a),"updateLlamaIndexConfig",0,p,"updatePageIndexConfig",0,m,"updateRagProviderMode",0,v,"uploadKnowledgeBaseFiles",0,H])},553254,a=>{"use strict";let b=(0,a.i(883706).default)("code-xml",[["path",{d:"m18 16 4-4-4-4",key:"1inbqp"}],["path",{d:"m6 8-4 4 4 4",key:"15zrgr"}],["path",{d:"m14.5 4-5 16",key:"e7oirm"}]]);a.s(["Code2",0,b],553254)},523025,a=>{"use strict";let b=(0,a.i(883706).default)("minus",[["path",{d:"M5 12h14",key:"1ays0h"}]]);a.s(["Minus",0,b],523025)}];

//# sourceMappingURL=_07gwuti._.js.map
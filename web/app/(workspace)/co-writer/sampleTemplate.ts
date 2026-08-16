const FENCE = "```";

export const CO_WRITER_SAMPLE_TEMPLATE = `# DeepTutor Co-Writer

> DeepTutor's built-in writing canvas for notes, reports, tutorials, and AI-assisted drafts.

### Features

- Support Standard Markdown / CommonMark / GFM for everyday writing
- Real-time preview for headings, tables, code, math, flowchart, and sequence diagrams
- AI editing workflows for rewrite, shorten, and expand
- Safe inline HTML for tags like <sub>, <sup>, <abbr>, and <mark>
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

${FENCE}python
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
${FENCE}

#### JSON message

${FENCE}json
{
  "capability": "chat",
  "message": "Explain Newton's second law with one worked example.",
  "tools": ["rag", "web_search"]
}
${FENCE}

#### HTML code

${FENCE}html
<section class="deeptutor-card">
  <h1>DeepTutor</h1>
  <p>Write, revise, and organize learning content with AI.</p>
</section>
${FENCE}

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
| \`deep_research\` | Multi-source research reports |
| \`visualize\` | Charts, diagrams, and interactive visuals |
| \`math_animator\` | Mathematical animations |

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

### Mermaid Flowchart

${FENCE}mermaid
flowchart TD
  question[Student asks a question] --> intent[DeepTutor analyzes intent]
  intent --> workflow{Need a deep workflow?}
  workflow -->|No| chat[Answer with chat]
  workflow -->|Yes| capability[Route to a capability]
  chat --> response[Return a structured response]
  capability --> response
${FENCE}

### Sequence Diagram

${FENCE}mermaid
sequenceDiagram
  Student->>DeepTutor: Ask for help
  DeepTutor->>KnowledgeBase: Load context
  Note right of DeepTutor: Collect memory and relevant knowledge
  DeepTutor-->>Student: Return a guided response
  Student->>DeepTutor: Request a rewrite in Co-Writer
${FENCE}

### End
`;

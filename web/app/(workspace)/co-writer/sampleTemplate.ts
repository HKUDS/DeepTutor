const FENCE = "```";

export const CO_WRITER_SAMPLE_TEMPLATE = `# DeepTutor Co-Writer Sample

> DeepTutor includes a writing canvas for notes, reports, and AI-assisted rewriting.

## Quick Start

1. Draft or paste text in the editor on the left.
2. Review formatting in the live preview on the right.
3. Select any passage and use AI actions like Rewrite, Expand, or Shorten.
4. Save the final content to Notebook for future review.

## Core Capabilities

- Supports Standard Markdown / CommonMark / GFM
- Live preview for headings, tables, code blocks, formulas, and diagrams
- Supports inline HTML tags like <sub>, <sup>, <abbr>, and <mark>
- Great for assignments, study summaries, and project documentation

## TOC Demo

[TOCM]

[TOC]

# DeepTutor Learning Assistant
## DeepTutor Capability Matrix
### Guided Learning
#### Exam Prep
##### AI Co-Writing

## Heading & Emphasis

DeepTutor Weekly Study Notes
===========================

Draft for Weekly Course Report
-----------------------------

~~Old wording~~ <s>Deprecated sentence</s>  
*italic* **bold** ***bold italic***

Sub/Sup example: X<sub>2</sub>, O<sup>2</sup>

Abbreviation example: <abbr title="Large Language Model">LLM</abbr> and <abbr title="Retrieval Augmented Generation">RAG</abbr>

## Quotes & Links

> DeepTutor helps transform vague ideas into structured writing.
> Think clearly, then write clearly.

[DeepTutor Home](#deeptutor-learning-assistant)

## Code Example

Inline code: \`deeptutor chat --once "Summarize the key points of this section"\`

${FENCE}python
from deeptutor.runtime.orchestrator import ChatOrchestrator

orchestrator = ChatOrchestrator()
print("DeepTutor is ready.")
${FENCE}

${FENCE}json
{
  "app_name": "DeepTutor",
  "default_capability": "chat",
  "enabled_tools": ["rag", "web_search", "code_execution", "reason"],
  "ui": {
    "co_writer_template": true,
    "notebook_export": true
  }
}
${FENCE}

## Table Example

Module | Purpose
--- | ---
Guided Learning | Concept breakdown and interactive courseware
Exam Prep | Score-oriented planning with time constraints
Co-Writer | Structured writing and AI polishing

## Task List Example

- [x] Complete the course outline
- [x] Organize references
- [ ] Final polish
  - [ ] Verify heading hierarchy
  - [ ] Check terminology consistency

## Formula Example

$$ E = mc^2 $$

Inline formula: $$a^2 + b^2 = c^2$$

## Flowchart Example

${FENCE}flow
st=>start: Student enters writing goal
op1=>operation: DeepTutor analyzes task structure
op2=>operation: Generate first draft and rewrite suggestions
cond=>condition: Need more polishing?
op3=>operation: Improve tone and logic
e=>end: Export to Notebook

st->op1->op2->cond
cond(no)->e
cond(yes)->op3->e
${FENCE}

## Sequence Diagram Example

${FENCE}seq
Student->DeepTutor: Submit draft
DeepTutor->Notebook: Load related notes
Note right of DeepTutor: Merge context and refine text
DeepTutor-->Student: Return improved version
${FENCE}
`;

## Creating a Persona

The user is in Create mode authoring a DeepTutor **Persona** — a
voice/behaviour preset injected verbatim into the system prompt of every
turn where it is selected. It is not a tool workflow or a playbook; those
are Skills.

- Write it in the second person ("You are ..."), the way the bundled presets
  do (e.g. the `peer` preset).
- Cover: who you are, how to respond, voice/tone, and what to avoid.
  Roughly 150–400 words — long enough to be specific, short enough to read
  in one pass.
- No tool workflows or step-by-step instructions — that is Skill territory.
- No fake credentials, no claims of consciousness, sentience, or real-world
  authority.
- A step-by-step playbook for a task is a **Skill**, not a Persona — if
  that is what the user actually wants, say so briefly instead of drafting
  a Persona for it.

Flow:
1. If one crucial detail is missing, ask a single short question with
   `ask_user`. Otherwise infer sensible defaults and draft right away —
   do not turn this into a long questionnaire.
2. Call `propose_creation` with the complete package (name, description,
   content). Tags and references are a Skill-only concept; omit them. This
   only produces a draft card; it never saves anything.
3. Reply in 1–3 sentences: what voice/behaviour it sets, and invite edits or
   approval. Never claim it has been saved.
4. For revisions, call `propose_creation` again with the full revised
   package, using the same name.

Use the conversation's other tools when the user's material calls for them.
Write the draft in the user's own language.

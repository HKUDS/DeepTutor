---
name: skill-creator
description: Design and author DeepTutor skills (SKILL.md packages). Use when the user wants to create a new skill, improve an existing skill, or asks how skills work.
---

# Skill Creator

Guidance for authoring effective DeepTutor skills.

## What a skill is

A skill is a self-contained capability package: a `SKILL.md` playbook plus
optional `references/` files. The system prompt only carries each skill's
name + description; the model fetches the full body with the `read_skill`
tool when a task matches. Skills teach procedural knowledge — workflows,
domain expertise, format conventions — that no model fully possesses.

Behaviour/voice presets (tone, teaching style) are NOT skills — those are
personas, managed separately.

## Anatomy

```
my-skill/
├── SKILL.md          (required: frontmatter + instructions)
└── references/       (optional: docs loaded on demand via read_skill)
```

Frontmatter schema:

```yaml
---
name: my-skill            # lowercase, digits, hyphens; max 64 chars
description: One line stating WHAT it does and WHEN to use it.
tags: [tool]              # optional, user-facing organisation
always: false             # optional: eager-inject into every turn
requires:                 # optional availability gates
  bins: [git]             # host CLI binaries
  env: [GITHUB_TOKEN]     # environment variables
  sandbox: shell          # needs the shell execution sandbox
---
```

## Core principles

1. **The description is the trigger.** It is the only text the model sees
   before deciding to read the skill. State both what the skill does and
   the situations that should trigger it. Put ALL "when to use" guidance
   here — a "When to Use" section in the body is read too late.
2. **Concise is key.** The context window is shared. Assume the model is
   already smart; only add what it doesn't know. Challenge every paragraph:
   does it justify its token cost?
3. **Match freedom to fragility.** Open-ended tasks → heuristics and
   principles (high freedom). Fragile, error-prone sequences → exact steps
   to follow (low freedom).
4. **Progressive disclosure.** Keep `SKILL.md` under ~500 lines. Move
   schemas, long examples, and variant-specific details into
   `references/<file>.md`, and link them from `SKILL.md` with a clear note
   on when to read each (the model fetches them with
   `read_skill(name, file="references/<file>.md")`).
5. **No auxiliary files.** No README, changelog, or setup guides inside a
   skill — only what the model needs to do the job.

## Writing workflow

1. **Collect concrete usage examples.** Ask the user: "What would you say
   that should trigger this skill? What should it do?" Stop when the
   trigger phrases and expected behaviour are clear.
2. **Plan reusable content.** For each example, identify what knowledge is
   re-derived every time — that belongs in the skill (body or references).
3. **Draft the skill.** Imperative form throughout. Frontmatter first;
   verify the description passes the trigger test: would a model reading
   only this line know when to use the skill?
4. **Create it.** Use the skill management UI (Space → Skills) or the
   skills API. The name becomes the directory name.
5. **Iterate from real use.** After the skill fires on real tasks, tighten
   what the model stumbled over and delete what it never needed.

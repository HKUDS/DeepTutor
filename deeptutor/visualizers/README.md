# DeepTutor visualizer package protocol

A visualizer type is a declarative agent contract plus a canvas renderer. User
packages are zip archives with this shape:

```text
fraction_tiles.zip
├── visualizer.json
├── index.html
├── renderer.js
└── renderer.css
```

`visualizer.json` describes when the agent should choose the type, the payload
it must generate, and the iframe entry point:

```json
{
  "id": "fraction_tiles",
  "version": "1.0.0",
  "display_name": "Fraction Tiles",
  "description": "Interactive comparison of fractions.",
  "subjects": ["mathematics"],
  "intents": ["compare", "explore"],
  "render_target": "iframe",
  "renderer_entry": "index.html",
  "payload_format": "application/json",
  "payload_kind": "json",
  "payload_schema": {
    "type": "object",
    "required": ["fractions"],
    "properties": {
      "fractions": {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1
      }
    },
    "additionalProperties": false
  },
  "prompt": "Return equivalent fractions that directly answer the learner's request."
}
```

Imported packages are intentionally declarative: they cannot ship Python or
register backend code. Their renderer runs in a script-only sandbox with no
network access. Local JSON Schema is validated before a payload reaches the
canvas; remote schema references are rejected.

When the iframe loads, the host sends:

```js
{
  type: "deeptutor:visualization:render",
  schema_version: "deeptutor.visualization/v1",
  renderer,
  payload,
  presentation,
  interaction
}
```

The renderer may send two messages back to its parent:

```js
parent.postMessage({
  type: "deeptutor:visualization:resize",
  height: document.documentElement.scrollHeight
}, "*");

parent.postMessage({
  type: "deeptutor:visualization:prompt",
  text: "Why are these fractions equivalent?"
}, "*");
```

Core native renderers and bundled optional types use the same versioned canvas
envelope. Their trusted validators and native React components live in the
host, while installation state remains per user.

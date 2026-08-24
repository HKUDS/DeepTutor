# deeptutor-reading-essentials

Optional Immersive Reading actions for DeepTutor. The core reader remains a
document renderer with secure extension slots; installing this distribution
adds five independently discoverable entry points:

- `guided_learn` — Learn
- `quiz` — Test
- `read_aloud` — Read aloud
- `translation` — Translate
- `vocabulary` — Vocabulary

## Release status

This package is currently a local pre-release. It requires a DeepTutor core
that provides the `deeptutor.reading_extensions` protocol. The published
`deeptutor==1.5.16` distribution does not yet contain that protocol, so do not
publish or install this package from PyPI until the protocol has been released
in a newer core version.

For the local monorepo, install it in editable mode:

```bash
python -m pip install -e packages/deeptutor-reading-essentials
```

All five actions appear when the package is installed. A Learning Account can
enable or disable individual extension IDs through its reading grant. Removing
the package hides the toolbar without affecting reading, progress, or
annotations.

## Security contract

Extensions are Python entry points, not browser JavaScript. DeepTutor verifies
the material, locator, selection, and visible text before invoking an action.
The package can return only the core-supported `card`, `quiz`, `feedback`, and
`browser_speech` result types.

## Translation

Set both variables to enable model-backed translation:

```bash
export DEEPTUTOR_READING_TRANSLATION_MODEL=<installed-model-id>
export DEEPTUTOR_READING_TRANSLATION_PROVIDER=<provider-binding>
```

The provider variable may be omitted when the model resolves through the
default binding. Missing or invalid provider configuration returns an
actionable card and never takes down the reader.

## Guided learning and quizzes

Learn and Test always have deterministic fallbacks. Without model configuration,
Learn extracts a page overview, concepts, and a reflection prompt; Test generates
three story-comprehension questions from the visible page. Vocabulary uses the
same built-in child dictionary and progressive thinking clues as the former Kids
reader, including stable three-choice prompts and Chinese meaning feedback.

To enable model-enhanced page guides:

```bash
export DEEPTUTOR_READING_LEARN_MODEL=<installed-model-id>
export DEEPTUTOR_READING_LEARN_PROVIDER=<provider-binding>
```

To enable model-enhanced comprehension quizzes:

```bash
export DEEPTUTOR_READING_QUIZ_MODEL=<installed-model-id>
export DEEPTUTOR_READING_QUIZ_PROVIDER=<provider-binding>
```

Provider variables may be omitted. Invalid or unavailable model responses fall
back to the local experience. Correct answers, explanations, and vocabulary
meanings remain server-side until a child submits an answer.

## Vocabulary

Set `DEEPTUTOR_READING_DICTIONARY` to override the built-in child dictionary
with a local JSON object:

```json
{
  "reticent": "reluctant to share information"
}
```

Values may be strings or arrays of strings. Definitions are truncated at 4,000
characters and the dictionary file is limited to 2 MB. Words not found in the
override fall back to the built-in child vocabulary.

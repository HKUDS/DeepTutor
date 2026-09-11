import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const component = readFileSync(
  path.resolve(process.cwd(), "components/reading/ReadingExtensionBar.tsx"),
  "utf8",
);
const pane = readFileSync(
  path.resolve(process.cwd(), "components/reading/ReaderPane.tsx"),
  "utf8",
);
const api = readFileSync(
  path.resolve(process.cwd(), "lib/reading-api.ts"),
  "utf8",
);
const english = readFileSync(
  path.resolve(process.cwd(), "locales/en/app.json"),
  "utf8",
);
const chinese = readFileSync(
  path.resolve(process.cwd(), "locales/zh/app.json"),
  "utf8",
);

test("the Reader toolbar is empty when no extension is installed", () => {
  assert.match(component, /if \(actions\.length === 0\) return null/);
  assert.match(pane, /<ReadingExtensionBar/);
});

test("extension results never inject browser JavaScript or raw HTML", () => {
  assert.doesNotMatch(component, /dangerouslySetInnerHTML|eval\(|new Function/);
  assert.match(component, /String\(result\.payload\.body/);
});

test("the browser sends a locator and selection, not trusted visible text", () => {
  assert.match(api, /runReadingExtension/);
  assert.doesNotMatch(api, /visible_text\?: string/);
});

test("a malformed extension catalog cannot crash the whole reader", () => {
  assert.match(api, /if \(!Array\.isArray\(payload\)\) return \[\]/);
  assert.match(
    api,
    /Array\.isArray\(\(row as ReadingExtensionManifest\)\.actions\)/,
  );
});

test("browser speech is stoppable and cannot continue after navigation", () => {
  assert.match(
    component,
    /const \[speaking, setSpeaking\] = useState\(false\)/,
  );
  assert.match(component, /function stopSpeaking\(\)/);
  assert.match(component, /window\.speechSynthesis\?\.cancel\(\)/);
  assert.match(component, /utterance\.onend = \(\) => setSpeaking\(false\)/);
  assert.match(component, /utterance\.onerror = \(\) => setSpeaking\(false\)/);
  assert.match(component, /\}, \[locator, materialId\]\);/);
  assert.match(component, /aria-label=\{t\("Stop reading aloud"\)\}/);
});

test("the built-in read-aloud action is localized", () => {
  assert.match(
    component,
    /extensionId === "read_aloud" && actionId === "read"/,
  );
  assert.match(english, /"Read aloud": "Read aloud"/);
  assert.match(chinese, /"Read aloud": "朗读"/);
  assert.match(english, /"Reading aloud": "Reading aloud"/);
  assert.match(chinese, /"Reading aloud": "正在朗读"/);
  assert.match(english, /"Stop reading aloud": "Stop reading aloud"/);
  assert.match(chinese, /"Stop reading aloud": "停止朗读"/);
});

test("the built-in study-guidance action is localized", () => {
  assert.match(component, /function builtInActionLabel/);
  assert.match(
    component,
    /extensionId === "guided_learning" && actionId === "guide"/,
  );
  assert.match(component, /t\(builtInLabel\)/);
  assert.match(english, /"Guide me": "Guide me"/);
  assert.match(chinese, /"Guide me": "引导我"/);
});

test("study-guidance steps are visible in the result card", () => {
  assert.match(component, /result\.payload\.steps/);
  assert.match(component, /steps\.map\(\(step, index\) =>/);
  assert.match(component, /list-decimal/);
});

test("the built-in vocabulary action is localized", () => {
  assert.match(
    component,
    /extensionId === "vocabulary" && actionId === "explain"/,
  );
  assert.match(english, /"Explain vocabulary": "Explain vocabulary"/);
  assert.match(chinese, /"Explain vocabulary": "解释词汇"/);
});

test("vocabulary terms are visible in the result card", () => {
  assert.match(component, /result\.payload\.terms/);
  assert.match(component, /String\(term\.term \|\| ""\)/);
  assert.match(component, /terms\.map\(\(term, index\) =>/);
  assert.match(component, /<dt className="font-medium">\{term\.term\}<\/dt>/);
  assert.match(component, /\{term\.meaning\}/);
  assert.match(component, /\{term\.usage\}/);
});

test("the built-in reading-quiz action is localized", () => {
  assert.match(component, /extensionId === "quiz" && actionId === "start"/);
  assert.match(component, /t\(builtInLabel\)/);
  assert.match(english, /"Quiz me": "Quiz me"/);
  assert.match(chinese, /"Quiz me": "测一测"/);
});

test("reading quizzes reveal grading only after the learner answers", () => {
  assert.match(component, /correct_choice_index\?: number/);
  assert.match(component, /const \[answers, setAnswers\] = useState/);
  assert.match(component, /aria-pressed=\{selected === choiceIndex\}/);
  assert.match(component, /selected === correctChoiceIndex/);
  assert.match(component, /t\("Correct"\).*t\("Incorrect"\)/s);
});

test("the built-in translation actions have explicit target languages", () => {
  assert.match(
    component,
    /extensionId === "translation" && actionId === "translate_en"/,
  );
  assert.match(
    component,
    /extensionId === "translation" && actionId === "translate_zh"/,
  );
  assert.match(english, /"Translate to English": "Translate to English"/);
  assert.match(chinese, /"Translate to Chinese": "翻译成中文"/);
});

test("translation results are rendered as text in the result card", () => {
  assert.match(component, /String\(result\.payload\.translation \|\| ""\)/);
  assert.match(component, /result\.payload\.alternatives/);
  assert.match(component, /String\(result\.payload\.note \|\| ""\)/);
  assert.match(component, /\{translation\.translation\}/);
  assert.match(component, /\{translation\.note\}/);
  assert.match(component, /translation\.alternatives\.map/);
});

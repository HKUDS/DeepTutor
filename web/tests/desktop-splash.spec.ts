import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The splash and the first-run wizard share one document, and Rust drives both
 * through `eval`. Two failure modes here are invisible at runtime and cost a
 * user the whole first launch:
 *
 * * a wizard-local `function showError` is shadowed by the `window.showError`
 *   assignment (which runs last), so wizard failures are written to the hidden
 *   splash node and the user sees nothing;
 * * an error node inside a hidden step is equally invisible — "could not read
 *   that folder" is a `step-data` failure, drawn inside `step-done`.
 */

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

const html = source("../desktop/web/index.html");
const wizard = html.slice(html.indexOf('<main id="wizard"'), html.indexOf("<script>"));

describe("desktop splash and wizard", () => {
  it("keeps the wizard's error surface separate from the splash's", () => {
    // The splash surface Rust calls through `eval`.
    expect(html).toMatch(/window\.showError\s*=/);
    expect(html).toMatch(/window\.setStatus\s*=/);
    // The wizard's own helper, under a name the assignment cannot shadow.
    expect(html).toMatch(/^\s*function showWizardError\(/m);
    expect(html).not.toMatch(/^\s*function showError\(/m);
    // ...and both call sites use it.
    expect(html.match(/showWizardError\(String\(error\)\)/g) ?? []).toHaveLength(2);
  });

  it("renders the wizard error outside every step", () => {
    expect(wizard).toMatch(/<p class="error" id="wizard-error"/);
    const before = wizard.slice(0, wizard.indexOf('id="wizard-error"'));
    const opened = (before.match(/<section class="step"/g) ?? []).length;
    const closed = (before.match(/<\/section>/g) ?? []).length;
    expect(opened).toBe(closed);
  });

  it("asks for a folder with nothing but a title", () => {
    // The shell's `PickOptions` defaults `filters`; sending it the shape the
    // wizard has always sent must stay valid.
    expect(html).toMatch(
      /invoke\("pick_folder",\s*\{\s*options:\s*\{\s*title:\s*copy\(\)\.dataHeading\s*\},?\s*\}\)/,
    );
  });
});

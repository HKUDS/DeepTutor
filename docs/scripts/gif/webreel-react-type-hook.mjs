const MARKER = "for (let i = 0; i < text.length; i++) {\n        const char = text[i];";

const HELPER = `async function syncReactField(client, value) {
    await client.Runtime.evaluate({
        expression: \`(() => {
          const fields = [...document.querySelectorAll("textarea")].filter((node) => {
            const box = node.getBoundingClientRect();
            return box.width > 40 && box.height > 16;
          });
          const field = fields.sort((left, right) => right.getBoundingClientRect().width - left.getBoundingClientRect().width)[0];
          if (!field) return;
          field.focus();
          const next = \${JSON.stringify(value)};
          const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value")?.set;
          if (setter) setter.call(field, next);
          else field.value = next;
          field.dispatchEvent(new InputEvent("input", { bubbles: true, data: next.slice(-1), inputType: "insertText" }));
        })()\`,
    });
}
`;

export async function load(url, context, nextLoad) {
  const loaded = await nextLoad(url, context);
  if (!url.includes("/@webreel/core/dist/actions.js")) return loaded;
  const source = loaded.source.toString();
  if (!source.includes(MARKER)) {
    throw new Error("webreel typeText changed; update scripts/gif/webreel-react-type-hook.mjs");
  }
  return {
    format: loaded.format ?? "module",
    source: `${HELPER}\n${source.replace(
      MARKER,
      `${MARKER}\n        await syncReactField(client, text.slice(0, i + 1));`,
    )}`,
    shortCircuit: true,
  };
}

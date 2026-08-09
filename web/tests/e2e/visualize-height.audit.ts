import { test, expect } from "@playwright/test";
import { prepareIframeHtml } from "../../lib/iframe-html";

test("HTML visualization iframe shrinks and grows with tab content", async ({
  page,
}) => {
  await page.setContent(
    '<iframe id="visualization" style="width:640px;height:560px;border:0"></iframe>',
  );

  await page.evaluate(() => {
    const iframe = document.querySelector<HTMLIFrameElement>("#visualization");
    if (!iframe) throw new Error("Visualization iframe was not created");

    window.addEventListener("message", (event) => {
      if (event.source !== iframe.contentWindow) return;
      const data = event.data as { type?: string; height?: number };
      if (data?.type !== "dt:visualize-height" || typeof data.height !== "number") {
        return;
      }
      iframe.style.height = `${Math.min(2400, Math.max(240, Math.ceil(data.height) + 8))}px`;
    });
  });

  const html = prepareIframeHtml(`
    <!doctype html>
    <html>
      <head>
        <style>
          body { margin: 0; }
          #long-panel { height: 720px; background: #fee2e2; }
          #short-panel { height: 120px; background: #dbeafe; }
        </style>
      </head>
      <body>
        <button id="toggle" type="button">Toggle tab</button>
        <div id="long-panel"></div>
        <div id="short-panel" hidden></div>
        <script>
          const longPanel = document.querySelector("#long-panel");
          const shortPanel = document.querySelector("#short-panel");
          document.querySelector("#toggle").addEventListener("click", () => {
            longPanel.hidden = !longPanel.hidden;
            shortPanel.hidden = !shortPanel.hidden;
          });
          setTimeout(() => {
            const image = new Image();
            image.alt = "";
            image.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='160'%3E%3Crect width='320' height='160' fill='%23bfdbfe'/%3E%3C/svg%3E";
            image.onload = () => shortPanel.appendChild(image);
          }, 25);
        </script>
      </body>
    </html>
  `);

  const iframe = page.locator("#visualization");
  await iframe.evaluate((element, srcdoc) => {
    (element as HTMLIFrameElement).srcdoc = srcdoc;
  }, html);

  const frame = page.frames().find((candidate) => candidate !== page.mainFrame());
  if (!frame) throw new Error("Visualization iframe document was not created");

  await frame.locator("#short-panel img").waitFor({ state: "attached" });

  await expect
    .poll(() => iframe.evaluate((element) => parseFloat(element.style.height)))
    .toBeGreaterThan(700);
  const expandedHeight = await iframe.evaluate((element) =>
    parseFloat(element.style.height),
  );

  await frame.locator("#toggle").click();
  await expect
    .poll(() => iframe.evaluate((element) => parseFloat(element.style.height)))
    .toBeLessThan(expandedHeight - 100);
  const collapsedHeight = await iframe.evaluate((element) =>
    parseFloat(element.style.height),
  );
  expect(collapsedHeight).toBeGreaterThanOrEqual(240);

  await frame.locator("#toggle").click();
  await expect
    .poll(() => iframe.evaluate((element) => parseFloat(element.style.height)))
    .toBeGreaterThan(collapsedHeight + 100);

  await frame.locator("#toggle").evaluate((button) => {
    const toggle = button as HTMLButtonElement;
    toggle.click();
    toggle.click();
    toggle.click();
  });
  await expect
    .poll(() => iframe.evaluate((element) => parseFloat(element.style.height)))
    .toBeLessThan(expandedHeight - 100);
});

/**
 * Helpers for rendering AI-generated HTML inside a sandboxed `<iframe>`:
 * - {@link injectKaTeX} ensures the page can render `$...$` / `$$...$$`
 *   even if the model didn't include KaTeX itself.
 * - {@link sanitizeIframeHtml} strips navigation escapes while leaving
 *   interactive scripts isolated by the caller's sandboxed iframe.
 *
 * These were originally written for the (now-deprecated) Guided Learning
 * page; the visualize capability now reuses them for `render_mode=html`.
 */

const KATEX_RESOURCES = [
  '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" crossorigin="anonymous">',
  '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" crossorigin="anonymous"><' +
    "/script>",
  '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" crossorigin="anonymous"><' +
    "/script>",
].join("\n  ");

const KATEX_INIT_SCRIPT =
  "<script data-katex-init>" +
  'document.addEventListener("DOMContentLoaded",function(){var t=0,i=setInterval(function(){if(typeof renderMathInElement==="function"){clearInterval(i);try{renderMathInElement(document.body,{delimiters:[{left:"$$",right:"$$",display:true},{left:"$",right:"$",display:false},{left:"\\\\(",right:"\\\\)",display:false},{left:"\\\\[",right:"\\\\]",display:true}],throwOnError:false})}catch(e){console.error("[KaTeX] Error:",e)}}else if(++t>50){clearInterval(i);console.warn("[KaTeX] Timeout")}},100)});' +
  "<" +
  "/script>";

const KATEX_HEAD = KATEX_RESOURCES + "\n  " + KATEX_INIT_SCRIPT;

/**
 * Inject KaTeX (CSS + JS + auto-render init) into the document's `<head>`.
 * No-op if the document already references KaTeX.
 */
export function injectKaTeX(html: string): string {
  const lower = html.toLowerCase();
  const hasKaTeX =
    lower.includes("katex.min.css") ||
    lower.includes("katex.min.js") ||
    lower.includes("katex@") ||
    lower.includes("cdn.jsdelivr.net/npm/katex") ||
    lower.includes("unpkg.com/katex");

  if (hasKaTeX) return html;

  if (html.includes("</head>")) {
    return html.replace("</head>", KATEX_HEAD + "\n</head>");
  }
  if (html.includes("<head>")) {
    return html.replace(/<head([^>]*)>/i, "<head$1>\n" + KATEX_HEAD);
  }
  if (html.includes("<html")) {
    return html.replace(
      /(<html[^>]*>)/i,
      '$1\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n' +
        KATEX_HEAD +
        "\n</head>",
    );
  }

  return (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n' +
    KATEX_HEAD +
    "\n</head>\n<body>\n" +
    html +
    "\n</body>\n</html>"
  );
}

/**
 * Light defense-in-depth on top of `sandbox="allow-scripts"` (without
 * `allow-same-origin`): strip `javascript:` URLs and (best-effort) any
 * `<a target="_top">` / `target="_parent"` so a misbehaving model cannot
 * navigate the parent frame. We deliberately keep `<script>` tags and
 * inline `on*=` handlers because the model is *expected* to ship
 * interactive JS — and the sandbox already isolates it in a null origin
 * with no access to the host page.
 */
export function sanitizeIframeHtml(html: string): string {
  return html
    .replace(
      /\s(href|src|formaction)\s*=\s*(['"])\s*javascript:[\s\S]*?\2/gi,
      "",
    )
    .replace(/\starget\s*=\s*(['"])_(top|parent)\1/gi, ' target="_self"');
}

/**
 * Bridge injected into every widget iframe. The iframe runs in a null origin
 * (sandbox="allow-scripts", no allow-same-origin), so it talks to the host only
 * via postMessage:
 *   - `window.sendPrompt(text)` → posts a follow-up question; the host prefills
 *     it into the composer (the widget analogue of an SVG node's data-prompt).
 *   - observers post the current body content height so the host can grow and
 *     shrink the iframe instead of retaining an old viewport height.
 */
const BRIDGE_SCRIPT =
  `<script data-dt-bridge>
(function () {
  window.sendPrompt = function (text) {
    try {
      parent.postMessage({
        type: "dt:visualize-prompt",
        text: String(text || "")
      }, "*");
    } catch (error) {}
  };

  function reportHeight() {
    try {
      var body = document.body;
      var root = document.documentElement;
      // root.scrollHeight is at least the iframe viewport height. Once the host
      // grows that viewport it becomes a historical floor, so body content is
      // the primary measurement and the root is only a defensive fallback.
      var height = body && body.scrollHeight > 0
        ? body.scrollHeight
        : root.scrollHeight;
      if (!height || !isFinite(height)) height = root.scrollHeight || 0;
      parent.postMessage({
        type: "dt:visualize-height",
        height: height
      }, "*");
    } catch (error) {}
  }

  var scheduledFrame = 0;
  function scheduleHeightReport() {
    if (scheduledFrame) return;
    var run = function () {
      scheduledFrame = 0;
      reportHeight();
    };
    scheduledFrame = typeof requestAnimationFrame === "function"
      ? requestAnimationFrame(run)
      : setTimeout(run, 0);
  }

  function startHeightObservers() {
    try {
      var body = document.body;
      if (body && typeof ResizeObserver !== "undefined") {
        var resizeObserver = new ResizeObserver(scheduleHeightReport);
        resizeObserver.observe(body);
      }
      if (body && typeof MutationObserver !== "undefined") {
        var mutationObserver = new MutationObserver(scheduleHeightReport);
        mutationObserver.observe(body, {
          attributes: true,
          characterData: true,
          childList: true,
          subtree: true
        });
      }
      scheduleHeightReport();
    } catch (error) {
      reportHeight();
    }
  }

  // Gate on document.body, not readyState. This script is injected just
  // before </body>, so the body already exists while readyState is still
  // "loading" — and deferred scripts (the KaTeX tags injectKaTeX adds) must
  // all run before DOMContentLoaded fires. Waiting for that event means a
  // blocked or slow CDN leaves the observers unattached and every
  // visualization frozen at the iframe's initial height.
  if (document.body) {
    startHeightObservers();
  } else {
    document.addEventListener("DOMContentLoaded", startHeightObservers, { once: true });
  }
  window.addEventListener("load", scheduleHeightReport);
})();
<` + "/script>";

function injectBridge(html: string): string {
  if (html.includes("</body>")) {
    return html.replace("</body>", BRIDGE_SCRIPT + "\n</body>");
  }
  if (html.includes("</html>")) {
    return html.replace("</html>", BRIDGE_SCRIPT + "\n</html>");
  }
  return html + "\n" + BRIDGE_SCRIPT;
}

/**
 * Convenience: inject KaTeX, sanitize, then add the host bridge. Suitable for a
 * one-shot iframe `srcdoc` write.
 */
export function prepareIframeHtml(html: string): string {
  return injectBridge(sanitizeIframeHtml(injectKaTeX(html)));
}

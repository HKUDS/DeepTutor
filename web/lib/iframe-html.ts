/**
 * Helpers for rendering AI-generated HTML inside a sandboxed `<iframe>`:
 * - {@link injectKaTeX} ensures the page can render `$...$` / `$$...$$`
 *   even if the model didn't include KaTeX itself.
 * - {@link sanitizeIframeHtml} strips bare `<script>` blocks (except the
 *   KaTeX init shim) and any inline event handlers / `javascript:` URLs.
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

type IframeTheme = "light" | "dark";

function buildThemeStyle(theme: IframeTheme): string {
  if (theme !== "dark") {
    return `<style data-deeptutor-theme>
      :root { color-scheme: light; --dt-bg: #ffffff; --dt-panel: #f8fafc; --dt-card: #ffffff; --dt-border: #d8e0eb; --dt-text: #111827; --dt-muted: #667085; --dt-track: #d9e2ee; }
      html, body { background: var(--dt-bg); color: var(--dt-text); }
    </style>`;
  }

  // Dark mode: set CSS custom properties and override ONLY html/body.
  // The generated widget's own @media (prefers-color-scheme: dark) block
  // handles element-level styling. We avoid broad !important overrides on
  // generic elements (div, section, main …) which broke custom layouts.
  return `<style data-deeptutor-theme>
    :root { color-scheme: dark; --dt-bg: transparent; --dt-panel: rgba(255,255,255,0.05); --dt-card: rgba(255,255,255,0.05); --dt-border: rgba(255,255,255,0.1); --dt-text: #f5f1eb; --dt-muted: #b8aea6; --dt-track: #5a514b; }
    html, body { background: transparent !important; color: var(--dt-text) !important; }
    body { scrollbar-color: #5f5650 var(--dt-bg); }
    /* Expose a prefers-color-scheme override so widget CSS that checks the
       media query still triggers in dark mode even inside a sandboxed iframe. */
    @media (prefers-color-scheme: light) {
      :root { color-scheme: dark; }
    }
    /* Override inline-style white/light backgrounds that LLMs hardcode on divs */
    [style*="background: white"],
    [style*="background-color: white"],
    [style*="background:#fff"],
    [style*="background: #fff"],
    [style*="background:#ffffff"],
    [style*="background: #ffffff"],
    [style*="background-color:#fff"],
    [style*="background-color: #fff"],
    [style*="background-color:#ffffff"],
    [style*="background-color: #ffffff"] {
      background: transparent !important;
      background-color: transparent !important;
    }
    /* Override inline-style black text for readability */
    [style*="color: black"], [style*="color:black"],
    [style*="color: #000"], [style*="color:#000"],
    [style*="color: #000000"], [style*="color:#000000"] {
      color: var(--dt-text) !important;
    }
    /* Minimal fallback for widgets that don't handle dark mode themselves —
       only target inputs and SVG text, not layout containers. */
    input[type="range"] { color-scheme: dark; }
    svg text, svg tspan { fill: currentColor; }
    svg { background: transparent !important; }
  </style>`;
}

function injectThemeStyle(html: string, theme: IframeTheme): string {
  const themeStyle = buildThemeStyle(theme);
  if (html.includes("</head>")) {
    return html.replace("</head>", themeStyle + "\n</head>");
  }
  if (html.includes("<head>")) {
    return html.replace(/<head([^>]*)>/i, "<head$1>\n" + themeStyle);
  }
  if (html.includes("<html")) {
    return html.replace(
      /(<html[^>]*>)/i,
      '$1\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n' +
        themeStyle +
        "\n</head>",
    );
  }
  return (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n' +
    themeStyle +
    "\n</head>\n<body>\n" +
    html +
    "\n</body>\n</html>"
  );
}

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
 * Convenience: inject KaTeX, then sanitize. Suitable for a one-shot iframe
 * `srcdoc` write.
 */
export function prepareIframeHtml(
  html: string,
  theme: IframeTheme = "light",
): string {
  return sanitizeIframeHtml(injectThemeStyle(injectKaTeX(html), theme));
}

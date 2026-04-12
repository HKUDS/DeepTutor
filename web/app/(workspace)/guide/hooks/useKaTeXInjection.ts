/**
 * Hook for injecting KaTeX support into HTML content
 */
export function useKaTeXInjection() {
  /**
   * Inject KaTeX CSS and JS into HTML if not already present
   */
  const injectKaTeX = (html: string): string => {
    const katexInjection = `  <link data-katex-host="1" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
  <link data-katex-host="1" rel="stylesheet" href="https://unpkg.com/katex@0.16.9/dist/katex.min.css">
  <script>
    (function () {
      function renderMath() {
        if (typeof window.renderMathInElement !== "function") return false;
        try {
          window.renderMathInElement(document.body, {
            delimiters: [
              { left: "$$", right: "$$", display: true },
              { left: "\\\\[", right: "\\\\]", display: true },
              { left: "$", right: "$", display: false },
              { left: "\\\\(", right: "\\\\)", display: false }
            ],
            throwOnError: false,
            strict: "ignore"
          });
          return true;
        } catch (_error) {
          return false;
        }
      }

      function loadScript(src, done) {
        var script = document.createElement("script");
        script.src = src;
        script.defer = true;
        script.onload = done;
        script.onerror = done;
        document.head.appendChild(script);
      }

      function ensureKaTeX() {
        if (renderMath()) return;

        var ensureAutoRender = function () {
          if (typeof window.renderMathInElement === "function") {
            renderMath();
            return;
          }
          loadScript("https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js", function () {
            if (typeof window.renderMathInElement !== "function") {
              loadScript("https://unpkg.com/katex@0.16.9/dist/contrib/auto-render.min.js", function () {
                renderMath();
              });
              return;
            }
            renderMath();
          });
        };

        if (typeof window.katex === "undefined") {
          loadScript("https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js", function () {
            if (typeof window.katex === "undefined") {
              loadScript("https://unpkg.com/katex@0.16.9/dist/katex.min.js", function () {
                ensureAutoRender();
              });
              return;
            }
            ensureAutoRender();
          });
          return;
        }
        ensureAutoRender();
      }

      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", ensureKaTeX);
      } else {
        ensureKaTeX();
      }
      window.setTimeout(ensureKaTeX, 400);
      window.setTimeout(ensureKaTeX, 1500);
    })();
  </script>`;

    // Try to inject into </head> section (most common case)
    if (html.includes("</head>")) {
      return html.replace("</head>", `${katexInjection}\n</head>`);
    }

    // If no </head> tag, try to inject after <head> tag
    if (html.includes("<head>")) {
      return html.replace(/<head([^>]*)>/i, `<head$1>\n${katexInjection}`);
    }

    // If HTML structure exists but no <head>, add it
    if (html.includes("<html")) {
      return html.replace(
        /(<html[^>]*>)/i,
        `$1\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n${katexInjection}\n</head>`,
      );
    }

    // If no HTML structure, wrap it with full HTML document
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
${katexInjection}
</head>
<body>
${html}
</body>
</html>`;
  };

  return { injectKaTeX };
}

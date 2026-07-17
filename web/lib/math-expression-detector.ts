/**
 * math-expression-detector.ts
 *
 * Extracts mathematical expressions / function definitions from freeform text
 * (chat messages, LLM responses) and normalises them into strings that Desmos
 * can parse directly.
 *
 * Exported API:
 *   extractMathExpressions(text)  → string[]   (deduplicated, ordered)
 *   hasMathContent(text)          → boolean    (quick check, no allocation)
 */

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Strip LaTeX wrappers that Desmos won't accept verbatim. Best-effort. */
function normalizeLatex(raw: string): string {
  return raw
    .replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, "($1)/($2)")
    .replace(/\\sqrt\{([^}]*)\}/g, "sqrt($1)")
    .replace(/\\sqrt\s+(\S+)/g, "sqrt($1)")
    .replace(/\\left\(/g, "(")
    .replace(/\\right\)/g, ")")
    .replace(/\\left\[/g, "[")
    .replace(/\\right\]/g, "]")
    .replace(/\\cdot/g, "*")
    .replace(/\\times/g, "*")
    .replace(/\\div/g, "/")
    .replace(/\\pi/g, "pi")
    .replace(/\\theta/g, "theta")
    .replace(/\\alpha/g, "alpha")
    .replace(/\\beta/g, "beta")
    .replace(/\\infty/g, "infinity")
    .replace(/\\ln/g, "ln")
    .replace(/\\log/g, "log")
    .replace(/\\sin/g, "sin")
    .replace(/\\cos/g, "cos")
    .replace(/\\tan/g, "tan")
    .replace(/\\[a-zA-Z]+/g, "")
    .replace(/\{/g, "(")
    .replace(/\}/g, ")")
    .trim();
}

/** Remove surrounding whitespace and common prose wrapping. */
function cleanRaw(raw: string): string {
  return raw.replace(/^[`'"]+|[`'"]+$/g, "").trim();
}

/* ------------------------------------------------------------------ */
/*  Extraction rules                                                   */
/* ------------------------------------------------------------------ */

interface ExtractionRule {
  pattern: RegExp;
  group: number;
  normalize?: (s: string) => string;
}

const RULES: ExtractionRule[] = [
  // Display math blocks $$...$$
  { pattern: /\$\$([\s\S]*?)\$\$/g, group: 1, normalize: normalizeLatex },
  // Inline math $...$
  { pattern: /\$([^$\n]{2,80})\$/g, group: 1, normalize: normalizeLatex },
  // Explicit function definitions: f(x) = ..., y = ..., g(t) = ...
  {
    pattern: /\b([a-zA-Z](?:\([a-zA-Z]\))?\s*=\s*[^,;\n]{3,80})/g,
    group: 1,
    normalize: normalizeLatex,
  },
  // Common function calls: sin(x), cos(2x), sqrt(x+1)
  {
    pattern:
      /\b((?:sin|cos|tan|asin|acos|atan|sinh|cosh|tanh|sqrt|log|ln|abs|exp)\([^()]{1,40}\))/g,
    group: 1,
  },
  // Polynomial-like: 2x^2 + 3x - 5  or  x^2 + 5  etc.
  {
    pattern:
      /(-?[\d.]*\s*[a-z]\^[\d]+(?:\s*[+\-]\s*[\d.]*\s*[a-z]?[\^]?[\d]*)*)/g,
    group: 1,
  },
  // Famous physics: E = mc^2, F = ma
  { pattern: /\b([A-Z]\s*=\s*[a-zA-Z0-9^*/\s.]{2,30})/g, group: 1 },
];

/* ------------------------------------------------------------------ */
/*  Filters                                                            */
/* ------------------------------------------------------------------ */

function isLikelyExpression(s: string): boolean {
  if (s.length < 3) return false;
  // Must contain at least one variable or operator
  if (!/[x-zX-Z^=+\-*/()\\d\\\\]/.test(s)) return false;
  // Must contain at least one numeric or algebraic indicator
  if (!/[\d^=+\-*/]|sin|cos|tan|log|sqrt|ln/.test(s)) return false;
  // Reject pure prose
  if (/^[A-Za-z\s,.\-]+$/.test(s)) return false;
  return true;
}

const BLOCKLIST = [
  /^[A-Z]\s*=\s*[A-Z][a-z]+/, // "V = Velocity"
  /^[A-Z]\s*=\s*[A-Z][A-Z]+/, // "F = MA" (all caps noise)
  // Block equations that have no variables (letters) on the right side.
  // For example: "x = 180 - 120", "x = 60°", "x = 60**"
  /^[a-zA-Z]\s*=\s*[^a-zA-Z]+$/, 
];

function isBlocked(s: string): boolean {
  return BLOCKLIST.some((re) => re.test(s));
}

/* ------------------------------------------------------------------ */
/*  Public API                                                         */
/* ------------------------------------------------------------------ */

/**
 * Extracts and normalises mathematical expressions from `text`.
 * Returns a deduplicated, ordered array of Desmos-ready strings.
 */
export function extractMathExpressions(text: string): string[] {
  const seen = new Set<string>();
  const results: string[] = [];

  for (const rule of RULES) {
    const re = new RegExp(rule.pattern.source, rule.pattern.flags);
    let match: RegExpExecArray | null;
    while ((match = re.exec(text)) !== null) {
      const raw = rule.group === 0 ? match[0] : (match[rule.group] ?? "");
      let expr = cleanRaw(raw);
      if (rule.normalize) expr = rule.normalize(expr);
      expr = expr.trim();
      if (!expr || seen.has(expr)) continue;
      if (!isLikelyExpression(expr)) continue;
      if (isBlocked(expr)) continue;
      seen.add(expr);
      results.push(expr);
      if (results.length >= 10) break;
    }
    if (results.length >= 20) break;
  }

  return results;
}

/**
 * Quick check: does this text contain any math-like content?
 * Wider than before — catches equations in solution steps too.
 */
export function hasMathContent(text: string): boolean {
  // LaTeX math blocks
  if (/\$[\s\S]{2,}\$/.test(text)) return true;
  // Explicit function or variable definitions
  if (/\b[yfg]\s*(?:\([a-z]\))?\s*=/.test(text)) return true;
  // Powers like x^2, t^3
  if (/[a-zA-Z]\^[\d]/.test(text)) return true;
  // Common math functions
  if (/\b(?:sin|cos|tan|sqrt|log|ln)\s*\(/.test(text)) return true;
  // Famous equations
  if (/E\s*=\s*mc\^?2|F\s*=\s*ma/.test(text)) return true;
  // Polynomial patterns: 2x^2, 3x + 5, x^2 + ...
  if (/[\d.]*\s*[a-z]\^[\d]/.test(text)) return true;
  // Equals with variables: x = ..., y = ...
  if (/\b[a-z]\s*=\s*[-\d]/.test(text)) return true;
  return false;
}

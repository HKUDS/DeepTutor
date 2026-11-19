import {
  snippetCompletion,
  type Completion,
  type CompletionContext,
  type CompletionResult,
  type CompletionSource,
} from "@codemirror/autocomplete";

export type CodeLanguage = "python" | "c" | "cpp";

const PYTHON_KEYWORDS = [
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "False",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "None",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "True",
  "try",
  "while",
  "with",
  "yield",
];

const C_KEYWORDS = [
  "auto",
  "break",
  "case",
  "char",
  "const",
  "continue",
  "default",
  "do",
  "double",
  "else",
  "enum",
  "extern",
  "float",
  "for",
  "goto",
  "if",
  "inline",
  "int",
  "long",
  "register",
  "return",
  "short",
  "signed",
  "sizeof",
  "static",
  "struct",
  "switch",
  "typedef",
  "union",
  "unsigned",
  "void",
  "volatile",
  "while",
];

const CPP_KEYWORDS = [
  ...C_KEYWORDS,
  "bool",
  "catch",
  "class",
  "constexpr",
  "delete",
  "explicit",
  "false",
  "friend",
  "namespace",
  "new",
  "nullptr",
  "private",
  "protected",
  "public",
  "template",
  "throw",
  "true",
  "try",
  "typename",
  "using",
  "virtual",
];

const PYTHON_SNIPPETS: Completion[] = [
  snippetCompletion("for ${1:item} in ${2:items}:\n    ${3:pass}", {
    label: "for",
    detail: "for loop",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("while ${1:condition}:\n    ${2:pass}", {
    label: "while",
    detail: "while loop",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("if ${1:condition}:\n    ${2:pass}", {
    label: "if",
    detail: "if statement",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("def ${1:name}(${2:args}):\n    ${3:pass}", {
    label: "def",
    detail: "function",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("class ${1:Name}:\n    def __init__(self${2:, value}):\n        ${3:pass}", {
    label: "class",
    detail: "class",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("try:\n    ${1:pass}\nexcept ${2:Exception} as exc:\n    ${3:print(exc)}", {
    label: "try",
    detail: "try/except",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion('if __name__ == "__main__":\n    ${1:main()}', {
    label: "main",
    detail: "script entry point",
    type: "keyword",
    boost: 20,
  }),
];

const C_SNIPPETS: Completion[] = [
  snippetCompletion("for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n    ${3:/* body */}\n}", {
    label: "for",
    detail: "for loop",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("while (${1:condition}) {\n    ${2:/* body */}\n}", {
    label: "while",
    detail: "while loop",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("if (${1:condition}) {\n    ${2:/* body */}\n}", {
    label: "if",
    detail: "if statement",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("int main(void) {\n    ${1:return 0;}\n}", {
    label: "main",
    detail: "program entry point",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("struct ${1:Name} {\n    ${2:int value;}\n};", {
    label: "struct",
    detail: "struct definition",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("#include <stdio.h>\n\nint main(void) {\n    ${1:return 0;}\n}", {
    label: "stdio",
    detail: "C program skeleton",
    type: "keyword",
    boost: 20,
  }),
];

const CPP_SNIPPETS: Completion[] = [
  ...C_SNIPPETS,
  snippetCompletion("#include <iostream>\n\nint main() {\n    ${1:std::cout << \"hello\";}\n    return 0;\n}", {
    label: "iostream",
    detail: "C++ program skeleton",
    type: "keyword",
    boost: 20,
  }),
  snippetCompletion("for (auto ${1:item} : ${2:items}) {\n    ${3:/* body */}\n}", {
    label: "foreach",
    detail: "range-based for",
    type: "keyword",
    boost: 20,
  }),
];

export function keywordsFor(language: CodeLanguage): string[] {
  if (language === "python") return PYTHON_KEYWORDS;
  if (language === "cpp") return CPP_KEYWORDS;
  return C_KEYWORDS;
}

/**
 * Completion source for language keywords and snippets.
 *
 * This is the ordinary editor suggestion path: no network, no model. The
 * language package supplies syntax and indentation; this source supplies the
 * words a learner is most likely to type.
 */
export function keywordCompletionSource(language: CodeLanguage): CompletionSource {
  const keywords = keywordsFor(language);
  const snippets =
    language === "python"
      ? PYTHON_SNIPPETS
      : language === "cpp"
        ? CPP_SNIPPETS
        : C_SNIPPETS;

  return (context: CompletionContext): CompletionResult | null => {
    const word = context.matchBefore(/[A-Za-z_]\w*/);
    if (!word || (word.from === word.to && !context.explicit)) return null;

    const typed = word.text.toLowerCase();
    const options: Completion[] = [];
    for (const snippet of snippets) {
      const label = String(snippet.label || "");
      if (!typed || label.toLowerCase().startsWith(typed)) options.push(snippet);
    }
    for (const keyword of keywords) {
      if (!typed || keyword.toLowerCase().startsWith(typed)) {
        options.push({ label: keyword, type: "keyword" });
      }
    }
    return {
      from: word.from,
      options,
      validFor: /^[A-Za-z_]\w*$/,
    };
  };
}

/**
 * Completion source for identifiers already present in the document.
 *
 * Deliberately simple and local: this is the "suggestion" half of a normal
 * editor, not a language server. It reads the current document and offers
 * words the learner has already used, which is enough for a practice card.
 */
export function identifierCompletionSource(context: CompletionContext): CompletionResult | null {
  const word = context.matchBefore(/[A-Za-z_]\w*/);
  if (!word || (word.from === word.to && !context.explicit)) return null;

  const text = context.state.doc.toString();
  const names = new Set<string>();
  for (const match of text.matchAll(/[A-Za-z_]\w{2,}/g)) {
    names.add(match[0]);
  }
  if (names.size === 0) return null;

  const typed = word.text;
  return {
    from: word.from,
    options: Array.from(names)
      .filter((name) => name !== typed)
      .slice(0, 200)
      .map((label) => ({ label, type: "variable" })),
    validFor: /^[A-Za-z_]\w*$/,
  };
}

export function completionSources(language: CodeLanguage): CompletionSource[] {
  return [keywordCompletionSource(language), identifierCompletionSource];
}

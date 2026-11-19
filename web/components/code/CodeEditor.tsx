"use client";

import { useEffect, useRef } from "react";
import { EditorState } from "@codemirror/state";
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  acceptCompletion,
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
} from "@codemirror/autocomplete";
import {
  bracketMatching,
  defaultHighlightStyle,
  indentOnInput,
  indentUnit,
  syntaxHighlighting,
} from "@codemirror/language";
import { cpp } from "@codemirror/lang-cpp";
import { python } from "@codemirror/lang-python";

import { completionSources, type CodeLanguage } from "./completions";

interface CodeEditorProps {
  value: string;
  language: CodeLanguage;
  onChange: (value: string) => void;
  readOnly?: boolean;
  minHeight?: number;
  ariaLabel?: string;
}

function editorTheme(minHeight: number) {
  return EditorView.theme(
    {
      "&": {
        minHeight: `${minHeight}px`,
        backgroundColor: "transparent",
        color: "var(--foreground)",
        fontSize: "13px",
      },
      ".cm-scroller": {
        fontFamily:
          "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
        lineHeight: "1.55",
      },
      ".cm-content": {
        padding: "10px 0",
        caretColor: "var(--primary)",
      },
      ".cm-gutters": {
        backgroundColor: "transparent",
        color: "var(--muted-foreground)",
        border: "none",
        paddingRight: "6px",
      },
      ".cm-activeLine": {
        backgroundColor: "color-mix(in srgb, var(--primary) 7%, transparent)",
      },
      ".cm-activeLineGutter": {
        backgroundColor: "transparent",
      },
      "&.cm-focused": {
        outline: "none",
      },
      ".cm-selectionBackground, ::selection": {
        backgroundColor: "color-mix(in srgb, var(--primary) 24%, transparent)",
      },
      ".cm-cursor": {
        borderLeftColor: "var(--primary)",
      },
      ".cm-tooltip": {
        backgroundColor: "var(--card)",
        border: "1px solid var(--border)",
        color: "var(--foreground)",
        borderRadius: "8px",
      },
      ".cm-tooltip-autocomplete ul li[aria-selected]": {
        backgroundColor: "var(--primary)",
        color: "var(--primary-foreground, white)",
      },
      ".cm-panels": {
        backgroundColor: "var(--card)",
        color: "var(--foreground)",
      },
    },
    { dark: false },
  );
}

export default function CodeEditor({
  value,
  language,
  onChange,
  readOnly = false,
  minHeight = 180,
  ariaLabel = "Code editor",
}: CodeEditorProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<EditorView | null>(null);
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: valueRef.current,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightActiveLine(),
          drawSelection(),
          history(),
          bracketMatching(),
          closeBrackets(),
          indentOnInput(),
          indentUnit.of("    "),
          EditorState.tabSize.of(4),
          language === "python" ? python() : cpp(),
          syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
          autocompletion({
            activateOnTyping: true,
            override: completionSources(language),
            maxRenderedOptions: 50,
          }),
          keymap.of([
            { key: "Tab", run: acceptCompletion },
            ...defaultKeymap,
            ...historyKeymap,
            ...closeBracketsKeymap,
            ...completionKeymap,
            indentWithTab,
          ]),
          EditorView.lineWrapping,
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({
            "aria-label": ariaLabel,
            spellcheck: "false",
            autocapitalize: "off",
            autocomplete: "off",
          }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              onChangeRef.current(update.state.doc.toString());
            }
          }),
          editorTheme(minHeight),
        ],
      }),
    });
    viewRef.current = view;

    return () => {
      viewRef.current = null;
      view.destroy();
    };
  }, [ariaLabel, language, minHeight, readOnly]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: value },
    });
  }, [value]);

  return (
    <div
      ref={hostRef}
      className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--background)]"
      data-code-editor="true"
    />
  );
}

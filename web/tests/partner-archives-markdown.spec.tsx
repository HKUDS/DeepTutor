import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fromMarkdown } from "mdast-util-from-markdown";

import PartnerArchives from "@/components/partners/PartnerArchives";
import { makeFileLinkRemarkPlugin } from "@/components/common/InlineFileCard";

const api = vi.hoisted(() => ({ sessions: vi.fn(), historyPage: vi.fn() }));
const translate = vi.hoisted(() => (key: string) => key);
vi.mock("@/lib/partners-api", () => ({
  getPartnerSessions: api.sessions,
  getPartnerHistoryPage: api.historyPage,
  resumePartnerSession: vi.fn(),
  deletePartnerSession: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));

const markdown = "# 合成标题\n\n**合成重点**\n\n| 项目 | 状态 |\n| --- | --- |\n| 本地索引 | 就绪 |";
const userText = "请原样保留 **用户文字** 和 # |";

function session(lastMessage: string) {
  return {
    session_key: "web-synthetic",
    title: "Synthetic conversation",
    archived: false,
    message_count: 2,
    updated_at: "2026-10-19T10:00:00",
    last_message: lastMessage,
  };
}

beforeEach(() => {
  api.sessions.mockResolvedValue([session(markdown)]);
  api.historyPage.mockResolvedValue({
    messages: [
      { role: "user", content: userText },
      { role: "assistant", content: markdown },
    ],
    next_before: null,
  });
});
afterEach(cleanup);

const savedFile = {
  type: "document",
  filename: "report.md",
  mime_type: "text/markdown",
  url: "/files/workspace-items/ws_test/wsi_report",
  generated: true,
  origin: "workspace",
  relative_path: "outputs/chat/turn/report.md",
};
const rendererCases = ["", "<div>Archive context</div>\n\n"].flatMap((prefix) =>
  ["inline", "reference"].map((style) => ({ prefix, style })),
);

it("keeps reference handling opt-in for other file-provider consumers", () => {
  const tree = fromMarkdown("[Download][report] ![Chart][chart]\n\n[report]: outputs/chat/turn/report.md\n[chart]: outputs/chart.png");
  makeFileLinkRemarkPlugin([{ ...savedFile, origin: "workspace" }])?.()(
    tree as unknown as Record<string, unknown>,
  );
  expect(tree.children[0]).toMatchObject({
    type: "paragraph",
    children: [{ type: "linkReference" }, { type: "text" }, { type: "imageReference" }],
  });
  expect(tree.children[1]).toMatchObject({ type: "definition", url: savedFile.relative_path });
});

it.each(rendererCases)(
  "downloads a saved workspace file using $style Markdown with prefix $prefix",
  async ({ prefix, style }) => {
    api.historyPage.mockResolvedValue({
      messages: [{
        role: "assistant",
        content: prefix + (style === "reference"
          ? "[Download][RePoRt  FiLe]\n\n[ report file ]: outputs/chat/turn/report.md\n[REPORT FILE]: outputs/missing.md"
          : "[Download](outputs/chat/turn/report.md)"),
        attachments: [savedFile],
      }],
      next_before: null,
    });
    const downloads: { href: string | null; filename: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push({ href: this.getAttribute("href"), filename: this.download });
    });
    render(<PartnerArchives partnerId="synthetic" onToast={vi.fn()} />);

    const article = await screen.findByRole("article");
    const card = await within(article).findByRole("button", { name: "report.md" });
    expect(article.querySelector("a[href='outputs/chat/turn/report.md']")).toBeNull();
    fireEvent.click(card);
    expect(downloads).toEqual([{ href: savedFile.url, filename: savedFile.filename }]);
  },
);

it.each(rendererCases)(
  "keeps unresolved $style file paths as text with prefix $prefix",
  async ({ prefix, style }) => {
    api.historyPage.mockResolvedValue({
      messages: [{
        role: "assistant",
        content: prefix + (style === "reference"
          ? "[Unpublished report][missing] ![Unavailable chart][chart] [External][external] [Section][section] [Query][query] [App][app] [Undefined][no-definition]\n\n[missing]: outputs/missing.md\n[chart]: outputs/missing.png\n[external]: https://example.com/docs\n[section]: #section\n[query]: ?view=archive\n[app]: /settings"
          : "[Unpublished report](outputs/missing.md) ![Unavailable chart](outputs/missing.png) [External](https://example.com/docs) [Section](#section) [Query](?view=archive) [App](/settings)"),
      }],
      next_before: null,
    });
    render(<PartnerArchives partnerId="synthetic" onToast={vi.fn()} />);

    const article = await screen.findByRole("article");
    await within(article).findByText("Unpublished report", { exact: false });
    expect(article.querySelector("a[href='outputs/missing.md']")).toBeNull();
    expect(article.querySelector("img[src='outputs/missing.png']")).toBeNull();
    expect(article).toHaveTextContent("Unavailable chart");
    expect(within(article).getByRole("link", { name: "External" })).toHaveAttribute("href", "https://example.com/docs");
    expect(within(article).getByRole("link", { name: "Section" })).toHaveAttribute("href", "#section");
    expect(within(article).getByRole("link", { name: "Query" })).toHaveAttribute("href", "?view=archive");
    expect(within(article).getByRole("link", { name: "App" })).toHaveAttribute("href", "/settings");
    if (style === "reference") expect(article).toHaveTextContent("[Undefined][no-definition]");
  },
);

it.each(rendererCases)("resolves a saved $style workspace image with prefix $prefix", async ({ prefix, style }) => {
  api.historyPage.mockResolvedValue({
    messages: [{
      role: "assistant",
      content: prefix + (style === "reference"
        ? "![Published chart][chart]\n\n[chart]: outputs/chart.png"
        : "![Published chart](outputs/chart.png)"),
      attachments: [{
        ...savedFile,
        type: "image",
        filename: "chart.png",
        mime_type: "image/png",
        relative_path: "outputs/chart.png",
      }],
    }],
    next_before: null,
  });
  render(<PartnerArchives partnerId="synthetic" onToast={vi.fn()} />);

  const article = await screen.findByRole("article");
  expect(await within(article).findByRole("img", { name: "Published chart" })).toHaveAttribute("src", savedFile.url);
});

it("renders assistant Markdown with the real chat renderer and keeps user text literal", async () => {
  const onMessagesChange = vi.fn();
  const { container } = render(
    <PartnerArchives partnerId="synthetic" onToast={vi.fn()} onMessagesChange={onMessagesChange} />,
  );

  expect(await screen.findByRole("heading", { name: "合成标题" })).toBeInTheDocument();
  const article = screen.getByRole("article");
  expect(article.querySelector("strong")).toHaveTextContent("合成重点");
  expect(within(article).getByRole("table")).toHaveTextContent("本地索引");
  expect(within(article).getByRole("table").parentElement).toHaveClass("overflow-x-auto");
  expect(article).not.toHaveTextContent("**");
  const user = screen.getByText(userText);
  expect(user).toHaveClass("whitespace-pre-wrap");
  expect(user.querySelector("strong")).toBeNull();
  expect(container.querySelectorAll("table")).toHaveLength(1);
  expect(onMessagesChange).toHaveBeenLastCalledWith([
    { role: "user", content: userText },
    { role: "assistant", content: markdown },
  ]);
});

it.each([
  ["# 概览\n\n**重点**与[文档](https://example.com)", "概览 重点与文档"],
  ["| 名称 | 状态 |\n| --- | --- |\n| 本地 | 就绪 |", "名称 · 状态 本地 · 就绪"],
  ["名称 | 状态\n--- | ---\n本地 | 就绪", "名称 · 状态 本地 · 就绪"],
  ["**服务端截断的重点", "服务端截断的重点"],
])("shows readable plain text for conversation snippet %s", async (snippet, expected) => {
  api.sessions.mockResolvedValue([session(snippet)]);
  render(<PartnerArchives partnerId="synthetic" onToast={vi.fn()} />);

  const row = await screen.findByRole("button", { name: /Synthetic conversation/ });
  expect(row.querySelector("p")).toHaveTextContent(expected);
  expect(row.querySelector("p")?.textContent).not.toMatch(/\*\*|#|\|/);
  expect(row.querySelector("strong,table,a")).toBeNull();
});

it.each([
  ["Calculate `2 ** 3`", "Calculate 2 ** 3"],
  ["Keep a__b unchanged", "Keep a__b unchanged"],
  ["Literal `**unfinished` code", "Literal **unfinished code"],
  ["Calculate `2 ** 3 ** 4`", "Calculate 2 ** 3 ** 4"],
  ["Keep `a__b__c` unchanged", "Keep a__b__c unchanged"],
  ["Literal ``a`b ** c ** d`` code", "Literal a`b ** c ** d code"],
  ["First `**a**` then ``__b__ `c` ~~d~~``", "First **a** then __b__ `c` ~~d~~"],
  ["Keep `a\n**b**` code", "Keep a **b** code"],
  ["Keep `# | [x](url) <tag> {{x}} [^1]` literal", "Keep # | [x](url) <tag> {{x}} [^1] literal"],
])("preserves literal punctuation in conversation snippet %s", async (snippet, expected) => {
  api.sessions.mockResolvedValue([session(snippet)]);
  render(<PartnerArchives partnerId="synthetic" onToast={vi.fn()} />);

  const row = await screen.findByRole("button", { name: /Synthetic conversation/ });
  expect(row.querySelector("p")?.textContent).toBe(expected);
});

it.each([
  ["| Header |\n| --- |\n| Value |", "Header Value"],
  ["| A | B |\n| - | - |\n| x | y |", "A · B x · y"],
  ["| A | B |\n| - | - |\n| x\\|y | z |", "A · B x|y · z"],
  ["| A | B |\n| - | - |\n| `x\\|y` | z |", "A · B x|y · z"],
  ["A | B\n- | -\nx | y\n\nKeep a|b", "A · B x · y Keep a|b"],
  ["Just a paragraph\n--- | ---\nKeep this line", "Just a paragraph --- | --- Keep this line"],
])("preserves table cell content in conversation snippet %s", async (snippet, expected) => {
  api.sessions.mockResolvedValue([session(snippet)]);
  render(<PartnerArchives partnerId="synthetic" onToast={vi.fn()} />);

  const row = await screen.findByRole("button", { name: /Synthetic conversation/ });
  expect(row.querySelector("p")?.textContent).toBe(expected);
});

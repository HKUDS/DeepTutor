import { fireEvent, render, screen } from "@testing-library/react";
import { FileText } from "lucide-react";
import { useRef } from "react";
import { expect, it, vi } from "vitest";

import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/SessionViewerPanel";
import ContextReferenceTree from "@/components/chat/home/ContextReferenceTree";
import { InlineFileCardProvider } from "@/components/common/InlineFileCard";
import SimpleMarkdownRenderer from "@/components/common/SimpleMarkdownRenderer";
import { initI18n } from "@/i18n/init";
import { buildSessionActivity } from "@/lib/session-activity";

vi.mock("@/components/tasks/TaskPanelSection", () => ({
  default: () => null,
}));

initI18n("en");

function Conversation({
  markdown,
  onClose,
}: {
  markdown: string;
  onClose: () => void;
}) {
  const viewer = useRef<SessionViewerPanelHandle>(null);
  return (
    <>
      <InlineFileCardProvider
        attachments={[]}
        onOpen={(attachment) => viewer.current?.openFileTab(attachment)}
      >
        <SimpleMarkdownRenderer content={markdown} />
      </InlineFileCardProvider>
      <SessionViewerPanel
        ref={viewer}
        open
        sessionId="session-files"
        activity={buildSessionActivity([])}
        onClose={onClose}
        onAutoOpen={() => {}}
      />
    </>
  );
}

it("keeps an explicit return to the conversation inside the Activity view", async () => {
  const onClose = vi.fn();

  render(
    <SessionViewerPanel
      open
      sessionId="session-a"
      activity={buildSessionActivity([])}
      onClose={onClose}
      onAutoOpen={() => {}}
    />,
  );

  const back = await screen.findByRole("button", { name: "Back to conversation" });
  expect(back).toBeVisible();
  expect(back.parentElement).toHaveClass("sticky", "top-0");

  fireEvent.click(back);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("opens a stale file link inside the chat and returns to the same conversation", async () => {
  const url = "/files/outputs/workspace/chat/session/turn/missing.md";
  const fetch = vi.fn(async () => new Response(null, { status: 404 }));
  const onClose = vi.fn();
  vi.stubGlobal("fetch", fetch);

  try {
    render(<Conversation markdown={`[Meeting notes](${url}) [Draft notes](missing-draft.md)`} onClose={onClose} />);
    const file = screen.getByRole("link", { name: "Meeting notes" });
    expect(file.getAttribute("href")).toContain(url);
    expect(file).toHaveAttribute("data-chat-file-link");
    expect(fireEvent.click(file)).toBe(false);
    expect(await screen.findByText("This file is unavailable.")).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining(url), expect.objectContaining({ method: "HEAD" }));
    fireEvent.click(await screen.findByRole("button", { name: "Back to conversation" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByText("This file is unavailable.")).not.toBeInTheDocument();
    expect(file).toBeVisible();

    fetch.mockClear();
    const draft = screen.getByRole("link", { name: "Draft notes" });
    expect(draft).toHaveAttribute("href", "#chat-file-unavailable-missing-draft.md");
    expect(draft).toHaveAttribute("data-chat-file-link");
    expect(fireEvent.click(draft)).toBe(false);
    expect(await screen.findByText("This file is unavailable.")).toBeVisible();
    expect(fetch).not.toHaveBeenCalledWith(
      expect.stringContaining("missing-draft.md"),
      expect.anything(),
    );
  } finally {
    vi.unstubAllGlobals();
  }
});

it("marks uploaded attachment rows as file links and keeps their preview callback", () => {
  const onOpen = vi.fn();
  const url = "/files/attachments/session/upload/notes.pdf";
  render(
    <ContextReferenceTree
      items={[{
        key: "upload",
        icon: FileText,
        kind: "PDF",
        label: "notes.pdf",
        attachment: { type: "document", filename: "notes.pdf", url },
        onClick: onOpen,
      }]}
      summaryNoun="attachments"
      direction="down"
    />,
  );
  const row = screen.getByRole("link", { name: "PDF notes.pdf" });
  expect(row.getAttribute("href")).toContain(url);
  expect(row).toHaveAttribute("data-chat-file-link");
  expect(fireEvent.click(row)).toBe(false);
  expect(onOpen).toHaveBeenCalledOnce();
});

it("distinguishes unsupported snapshots from unavailable files with the same name", async () => {
  const snapshotUrl = `/files/workspace-items/ws_${"a".repeat(32)}/wsi_${"b".repeat(32)}`;
  const missingUrl = "/files/outputs/session/missing/archive.zip";
  const outputUrl = "/files/outputs/session/generated/archive.zip";
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(null, {
    status: url.includes(missingUrl) ? 404 : 200,
  })));

  try {
    render(<Conversation
      markdown={`[Stale archive](${missingUrl}) [Generated archive](${outputUrl}) [Published archive](${snapshotUrl})`}
      onClose={vi.fn()}
    />);
    fireEvent.click(screen.getByRole("link", { name: "Stale archive" }));
    expect(await screen.findByText("This file is unavailable.")).toBeVisible();

    fireEvent.click(screen.getByRole("link", { name: "Generated archive" }));
    expect(await screen.findByText("Preview is not available for this file type.")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Download" }).some((link) =>
      link.getAttribute("href")?.includes(outputUrl),
    )).toBe(true);

    fireEvent.click(screen.getByRole("link", { name: "Published archive" }));
    expect(await screen.findByText("Conversation snapshot")).toBeVisible();
    expect(screen.queryByText("This file is unavailable.")).not.toBeInTheDocument();
  } finally {
    vi.unstubAllGlobals();
  }
});

it("opens a published video lesson in the existing script-isolated player", async () => {
  const url = "/files/outputs/user/video_lesson/turn/artifacts/lesson.html";
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 200 })));

  try {
    render(<Conversation markdown={`[Lesson page](${url})`} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("link", { name: "Lesson page" }));
    const frame = await screen.findByTitle("lesson.html");
    expect(frame.getAttribute("src")).toContain(url);
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  } finally {
    vi.unstubAllGlobals();
  }
});

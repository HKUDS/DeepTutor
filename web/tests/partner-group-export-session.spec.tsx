import { useEffect } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import PartnerGroupPage from "@/app/(workspace)/partners/groups/[groupId]/page";
import { downloadChatMarkdown } from "@/lib/chat-export";
import type { PartnerGroupMessage } from "@/lib/partner-groups-api";
import { initI18n } from "@/i18n/init";

vi.mock("next/navigation", () => ({ useParams: () => ({ groupId: "group" }), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/partners/group/DiscussionModePicker", () => ({ default: () => null, useDiscussionModeLabel: () => () => "Panel" }));
vi.mock("@/lib/chat-export", () => ({ downloadChatMarkdown: vi.fn() }));
vi.mock("@/lib/partner-groups-api", () => ({
  getPartnerGroup: vi.fn(async () => ({ group_id: "group", name: "Research panel", members: [], member_ids: [], color: "#123456", discussion_mode: "panel_parallel" })),
  partnerGroupSessionKey: () => "A", createPartnerGroupSessionKey: () => "new", setPartnerGroupSessionKey: vi.fn(),
  deletePartnerGroup: vi.fn(), updatePartnerGroup: vi.fn(),
}));
vi.mock("@/components/partners/group/GroupSessionPicker", () => ({
  default: function GroupSessionPickerMock({ sessionKey, onSelect, onTitleChange }: { sessionKey: string; onSelect: (key: string) => void; onTitleChange: (title: string) => void }) {
    useEffect(() => { onTitleChange(`Discussion ${sessionKey}`); }, [sessionKey, onTitleChange]);
    return <button onClick={() => onSelect("B")}>Switch discussion</button>;
  },
}));
vi.mock("@/components/partners/group/PartnerGroupChat", () => ({
  default: ({ sessionKey, onMessagesChange }: { sessionKey: string; onMessagesChange: (messages: PartnerGroupMessage[]) => void }) => (
    <button onClick={() => onMessagesChange([
      { event_id: sessionKey, turn_id: "turn", session_key: sessionKey, role: "partner", content: `Answer ${sessionKey}`, author_id: "ada", author_name: "Ada", created_at: "", mentions: [], error: false, kind: "message", events: [], invocation_id: "", invocation: null },
    ])}>History loaded</button>
  ),
}));
initI18n("en");
it("clears the previous transcript on discussion switch and exports the new settled history with its title", async () => {
  render(<PartnerGroupPage />);
  expect(await screen.findByRole("button", { name: "Download" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "History loaded" }));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(downloadChatMarkdown).toHaveBeenLastCalledWith(
    [{ role: "assistant", speaker: "Ada", content: "Answer A" }], { title: "Research panel — Discussion A" },
  );
  fireEvent.click(screen.getByRole("button", { name: "Switch discussion" }));
  expect(screen.getByRole("button", { name: "Download" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "History loaded" }));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(downloadChatMarkdown).toHaveBeenLastCalledWith(
    [{ role: "assistant", speaker: "Ada", content: "Answer B" }], { title: "Research panel — Discussion B" },
  );
});

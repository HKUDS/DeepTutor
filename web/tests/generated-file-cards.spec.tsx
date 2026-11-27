import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GeneratedFileCards } from "@/features/chat/messages/ChatMessageList";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

function image(path: string, id: string): MessageAttachment {
  return {
    type: "image",
    filename: path.split("/").pop(),
    url: `/files/workspace-items/ws_test/${id}`,
    mime_type: "image/png",
    generated: true,
    origin: "workspace",
    workspace_id: "ws_test",
    workspace_item_id: id,
    relative_path: path,
  };
}

const figure = image("outputs/chat/turn-a/figure.png", "wsi_a");
const other = image("outputs/chat/turn-a/other.png", "wsi_b");

describe("generated image cards", () => {
  it("leaves out an image the reply already embeds inline", () => {
    render(
      <GeneratedFileCards
        attachments={[figure, other]}
        content="Here it is.\n\n![figure](outputs/chat/turn-a/figure.png)\n\nThe axis shows time."
      />,
    );
    expect(screen.queryByRole("img", { name: "figure.png" })).toBeNull();
    expect(screen.getByRole("img", { name: "other.png" })).toBeTruthy();
  });

  it("keeps every card when the reply does not embed the image", () => {
    render(<GeneratedFileCards attachments={[figure, other]} content="No images here." />);
    expect(screen.getAllByRole("img")).toHaveLength(2);
  });

  it("keeps the card when the reply only mentions the path in code", () => {
    render(
      <GeneratedFileCards
        attachments={[figure]}
        content={"Saved to:\n\n```\n![figure](outputs/chat/turn-a/figure.png)\n```"}
      />,
    );
    expect(screen.getByRole("img", { name: "figure.png" })).toBeTruthy();
  });

  it("does not hide a non-image file the reply links", () => {
    const report: MessageAttachment = {
      ...figure,
      type: "document",
      filename: "report.pdf",
      mime_type: "application/pdf",
      relative_path: "outputs/chat/turn-a/report.pdf",
      url: "/files/workspace-items/ws_test/wsi_c",
    };
    render(
      <GeneratedFileCards
        attachments={[report]}
        content="See [the report](outputs/chat/turn-a/report.pdf)."
      />,
    );
    expect(screen.getByText(/report/i)).toBeTruthy();
  });
});


it.each([
  "[Download](outputs/chat/turn-a/figure.png)",
  "Saved to outputs/chat/turn-a/figure.png",
  "`![figure](outputs/chat/turn-a/figure.png)`",
])("keeps the image preview when content only provides a link or example: %s", (content) => {
  render(<GeneratedFileCards attachments={[figure]} content={content} />);
  expect(screen.getByRole("img", { name: "figure.png" })).toBeTruthy();
});

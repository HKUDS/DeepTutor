import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Wand2 } from "lucide-react";
import { ComposerLead, type LeadToken } from "@/components/chat/home/ComposerLead";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it("renders a token's prefix in its own span, ahead of the label", () => {
  const token: LeadToken = {
    key: "create:skill",
    icon: Wand2,
    kind: "Create",
    prefix: "create",
    label: "skill",
    onRemove: vi.fn(),
  }
  render(<ComposerLead tokens={[token]} armed={false} hidden={false} onWidth={() => {}} />)
  const prefix = screen.getByText("create")
  const label = screen.getByText("skill")
  expect(prefix).toHaveClass("dt-lead-prefix")
  expect(label).toHaveClass("dt-lead-label")
  // Document order: the prefix reads before the kind's own label.
  expect(prefix.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it("omits the prefix span entirely for a token without one", () => {
  const token: LeadToken = {
    key: "skill:foo",
    icon: Wand2,
    kind: "Skills",
    label: "foo",
    onRemove: vi.fn(),
  }
  render(<ComposerLead tokens={[token]} armed={false} hidden={false} onWidth={() => {}} />)
  expect(screen.queryByText("create")).not.toBeInTheDocument()
  expect(document.querySelector(".dt-lead-prefix")).not.toBeInTheDocument()
})

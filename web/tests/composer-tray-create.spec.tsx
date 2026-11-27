import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ComposerTray } from "@/components/chat/home/ComposerTray";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

it("opens the Create menu and reports the picked kind", () => {
  const onChange = vi.fn()
  render(<ComposerTray placement="down" create={{ value: null, onChange }} />)
  fireEvent.click(screen.getByRole("button", { name: "Create" }))
  expect(screen.getByText("Skill")).toBeInTheDocument()
  expect(screen.getByText("Persona")).toBeInTheDocument()
  fireEvent.click(screen.getByText("Skill"))
  expect(onChange).toHaveBeenCalledWith("skill")
})

it("shows the chosen kind as the tray value, and clears it when picked again", () => {
  const onChange = vi.fn()
  render(<ComposerTray placement="down" create={{ value: "persona", onChange }} />)
  const trigger = screen.getByRole("button", { name: /Create/ })
  expect(trigger).toHaveAttribute("data-active", "true")
  fireEvent.click(trigger)
  fireEvent.click(screen.getByRole("option", { name: /Persona/ }))
  expect(onChange).toHaveBeenCalledWith(null)
})

it("hides the Create menu when the page customization turns it off", () => {
  const onChange = vi.fn()
  render(
    <ComposerTray
      placement="down"
      create={{ value: null, onChange }}
      controls={{ skills: true, mcp: true, partners: true, preferences: true, voice: true, create: false }}
    />,
  )
  expect(screen.queryByRole("button", { name: "Create" })).not.toBeInTheDocument()
})

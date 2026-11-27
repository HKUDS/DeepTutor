import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import McpServerForm from "@/components/mcp/McpServerForm";
import { ADMIN_MCP_SURFACE, SPACE_MCP_SURFACE } from "@/components/mcp/surface";
import { emptyMcpServerConfig } from "@/lib/mcp-api";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
it("keeps an existing admin origin approval visible and lets the operator revoke it", async () => {
  const save = vi.fn().mockResolvedValue(true);
  render(<McpServerForm surface={ADMIN_MCP_SURFACE} originalName="research" initialName="research"
    initialConfig={{ ...emptyMcpServerConfig(), type: "streamableHttp", url: "http://research.internal:8080/mcp", allow_private_network: true }}
    existingNames={["research"]} saving={false} onCancel={() => {}} onSave={save} />);
  const checkbox = screen.getByRole("checkbox", { name: /Approve this MCP origin/ });
  expect(checkbox).toBeChecked();
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][2].allow_private_network).toBe(false);
});
it("explains that an account selects an already approved origin rather than granting private access", async () => {
  const save = vi.fn().mockResolvedValue(true);
  render(<McpServerForm surface={SPACE_MCP_SURFACE} originalName="" initialName="research"
    initialConfig={{ ...emptyMcpServerConfig(), url: "http://research.internal:8080/mcp" }}
    existingNames={[]} saving={false} onCancel={() => {}} onSave={save} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /Use an administrator-approved/ }));
  expect(screen.getByText("Only this scheme, host and port can use private Docker or LAN addresses. Metadata addresses remain blocked.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][2].allow_private_network).toBe(true);
});

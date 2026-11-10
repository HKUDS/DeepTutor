import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import McpServerForm from "@/components/mcp/McpServerForm";
import McpServerRow from "@/components/mcp/McpServerRow";
import { SPACE_MCP_SURFACE } from "@/components/mcp/surface";
import { emptyMcpServerConfig } from "@/lib/mcp-api";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

// The Transport select is also a combobox and its label is not associated with
// the control, so the authentication select is identified the way a user reads
// it: the one offering the OAuth option.
function authenticationSelect(): HTMLSelectElement {
  const select = screen
    .getAllByRole("combobox")
    .find((el) =>
      Array.from(el.querySelectorAll("option")).some(
        (option) => option.textContent === "OAuth",
      ),
    );
  expect(select).toBeTruthy();
  return select as HTMLSelectElement;
}

it("saves a server added by URL with auth=oauth when OAuth is selected", async () => {
  // #2585: the form had no way to set MCPServerConfig.auth, so an OAuth-only
  // endpoint connected with no credentials and the row could never offer
  // Connect.
  const save = vi.fn().mockResolvedValue(true);
  render(<McpServerForm surface={SPACE_MCP_SURFACE} originalName="" initialName="notes-demo"
    initialConfig={emptyMcpServerConfig()}
    existingNames={[]} saving={false} onCancel={() => {}} onSave={save} />);
  fireEvent.change(screen.getByPlaceholderText("https://example.com/mcp"), {
    target: { value: "https://mcp.example.test/mcp" },
  });
  expect(authenticationSelect().value).toBe("");
  fireEvent.change(authenticationSelect(), { target: { value: "oauth" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][2].auth).toBe("oauth");
  expect(save.mock.calls[0][2].url).toBe("https://mcp.example.test/mcp");
});

it("defaults a new URL server to no auth and keeps a header-only save unchanged", async () => {
  const save = vi.fn().mockResolvedValue(true);
  render(<McpServerForm surface={SPACE_MCP_SURFACE} originalName="" initialName="notes-demo"
    initialConfig={emptyMcpServerConfig()}
    existingNames={[]} saving={false} onCancel={() => {}} onSave={save} />);
  fireEvent.change(screen.getByPlaceholderText("https://example.com/mcp"), {
    target: { value: "https://mcp.example.test/mcp" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][2].auth).toBe("");
});

it("initializes the select from an edited catalog server and keeps OAuth on save", async () => {
  const save = vi.fn().mockResolvedValue(true);
  const catalogConfig = {
    ...emptyMcpServerConfig(),
    type: "streamableHttp" as const,
    url: "https://mcp.example.test/mcp",
    auth: "oauth" as const,
    catalog_entry: "notes-demo",
  };
  render(<McpServerForm surface={SPACE_MCP_SURFACE} originalName="notes-demo" initialName="notes-demo"
    initialConfig={catalogConfig}
    existingNames={["notes-demo"]} saving={false} onCancel={() => {}} onSave={save} />);
  expect(authenticationSelect().value).toBe("oauth");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][2].auth).toBe("oauth");
  expect(save.mock.calls[0][2].catalog_entry).toBe("notes-demo");
});

it("offers Connect on the row exactly for a saved OAuth server", () => {
  const row = (auth: "" | "oauth") =>
    render(<McpServerRow name="notes-demo"
      cfg={{ ...emptyMcpServerConfig(), type: "streamableHttp", url: "https://mcp.example.test/mcp", auth }}
      status={undefined} isExpanded={false} saving={false}
      onToggleExpanded={() => {}} onToggleEnabled={() => {}} onEdit={() => {}} onDelete={() => {}}
      onAuthorize={() => {}} />);
  const oauth = row("oauth");
  expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
  oauth.unmount();
  row("");
  expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
});

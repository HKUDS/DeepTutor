import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProtocolMismatchNotice } from "@/features/chat/components/turn";
import { initI18n } from "@/i18n/init";

initI18n("en");

describe("protocol mismatch notice", () => {
  it("shows the client and server versions and reloads on request", async () => {
    const onReload = vi.fn();
    const user = userEvent.setup();
    render(
      <ProtocolMismatchNotice
        clientVersion="2.0"
        serverVersion="3.0"
        onReload={onReload}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("2.0");
    expect(screen.getByRole("alert")).toHaveTextContent("3.0");
    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalledOnce();
  });
});

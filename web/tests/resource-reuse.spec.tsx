import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  ResourceReuseContext,
  ResourceReuseControl,
  useResourceReusePolicy,
} from "@/components/chat/home/ResourceReuse";
import {
  DEFAULT_RESOURCE_REUSE,
  retainedKnowledgeBases,
} from "@/lib/resource-reuse";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
afterEach(cleanup);
function Harness({ scope, message }: { scope: string; message?: number }) {
  const reuse = useResourceReusePolicy(scope, message);
  return (
    <ResourceReuseContext.Provider value={reuse}>
      <ResourceReuseControl kind="books" />
    </ResourceReuseContext.Provider>
  );
}
it("keeps repeat choices per conversation when switching back", () => {
  const view = render(<Harness scope="first" />);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("checkbox")).toBeChecked();
  view.rerender(<Harness scope="second" />);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  view.rerender(<Harness scope="first" />);
  expect(screen.getByRole("checkbox")).toBeChecked();
});
it("retains knowledge and collaborating agents independently", () => {
  const names = ["book", "agent"];
  expect(
    retainedKnowledgeBases(names, new Set(["agent"]), {
      ...DEFAULT_RESOURCE_REUSE,
      knowledge: false,
    }),
  ).toEqual(["agent"]);
  expect(
    retainedKnowledgeBases(names, new Set(["agent"]), {
      ...DEFAULT_RESOURCE_REUSE,
      agent: false,
    }),
  ).toEqual(["book"]);
  expect(names).toEqual(["book", "agent"]);
});

it("preserves repeat policy when a sent draft receives its server ID", () => {
  const view = render(<Harness scope="draft_1" />);
  fireEvent.click(screen.getByRole("checkbox"));
  view.rerender(<Harness scope="draft_1" message={123} />);
  view.rerender(<Harness scope="server-id" message={123} />);
  expect(screen.getByRole("checkbox")).toBeChecked();
});

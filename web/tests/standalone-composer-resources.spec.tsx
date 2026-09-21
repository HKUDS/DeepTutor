import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

/**
 * The other half of #1534. `StandaloneComposer` owns the state pool every
 * non-chat surface shares, and it used to stop the resource trio at itself: a
 * caller could hand it a catalog, a selection and a setter, and `ChatComposer`
 * would still never see them — so the Skills row stayed off on mastery, quiz
 * follow-up and reading alike even where those surfaces had the data to show
 * it. This pins the pass-through, not the row's own rendering
 * (`composer-resources.spec.tsx` covers that).
 */
const seen = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));

vi.mock("@/components/chat/home/ChatComposer", () => ({
  default: (props: Record<string, unknown>) => {
    seen.props = props;
    return null;
  },
}));

const { default: StandaloneComposer } = await import(
  "@/components/chat/home/StandaloneComposer"
);

const CATALOG = {
  skills: [{ id: "s1", name: "Tutor" }],
  mcp: [{ id: "m1", name: "Filesystem" }],
};

type ResourceProps = {
  resourceCatalog?: typeof CATALOG;
  resourceSelection?: { skills: string[]; mcp: string[] };
  onResourceSelectionChange?: unknown;
};

/**
 * The composer fetches its model list on mount, so the render is wrapped in
 * `act` — the shared setup turns any "not wrapped in act" warning into a
 * failure, and this file is about props that already exist on the first pass.
 */
async function mount(
  resources: Partial<{
    resourceCatalog: typeof CATALOG;
    resourceSelection: { skills: string[]; mcp: string[] };
    onResourceSelectionChange: () => void;
  }>,
): Promise<ResourceProps> {
  await act(async () => {
    render(
      <StandaloneComposer
        onSubmit={() => undefined}
        onCancelStreaming={() => undefined}
        isStreaming={false}
        hasMessages={false}
        inputPlaceholder="Ask"
        {...resources}
      />,
    );
  });
  return seen.props as unknown as ResourceProps;
}

describe("StandaloneComposer resource pass-through", () => {
  it("forwards the catalog, the selection and the setter to ChatComposer", async () => {
    const props = await mount({
      resourceCatalog: CATALOG,
      resourceSelection: { skills: ["s1"], mcp: [] },
      onResourceSelectionChange: () => undefined,
    });

    expect(props.resourceCatalog).toEqual(CATALOG);
    expect(props.resourceSelection).toEqual({ skills: ["s1"], mcp: [] });
    expect(typeof props.onResourceSelectionChange).toBe("function");
  });

  it("leaves all three undefined for a surface that has nothing to offer", async () => {
    const props = await mount({});

    // Presence, not emptiness: `ChatComposer` hides a row when its catalog has
    // no entries, so a surface that never asked for one must not arrive looking
    // like it asked for an empty picker.
    expect(props.resourceCatalog).toBeUndefined();
    expect(props.resourceSelection).toBeUndefined();
    expect(props.onResourceSelectionChange).toBeUndefined();
  });
});

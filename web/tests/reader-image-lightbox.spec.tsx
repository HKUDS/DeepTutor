import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TextUnitView } from "@/components/reading/TextUnitView";
import { ReaderImageLightbox } from "@/components/reading/ReaderImageLightbox";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

// The text reader loads its unit and its embedded-picture index over the API;
// this file only cares about the pictures already in the DOM.
vi.mock("@/lib/reading-api", () => ({
  getMaterialMedia: async () => [],
  getUnitText: async () => ({ text: "A paragraph.\n", eof: true }),
  materialMediaUrl: (materialId: string, name: string) =>
    `/api/reading/materials/${materialId}/media/${name}`,
}));

vi.mock("@/lib/reading-outline", () => ({
  activeReaderHeading: () => null,
  extractReaderHeadings: () => [],
  readerLinesWithHeadings: (text: string) =>
    text
      .split("\n")
      .filter(Boolean)
      .map((line) => ({ text: line, heading: null, fence: false })),
}));

vi.mock("@/lib/reading-inline-markdown", () => ({
  imageMarkerNames: () => new Set<string>(),
  MarkdownLine: ({ text }: { text: string }) => <>{text}</>,
}));

vi.mock("@/lib/reading-w3c-annotations", () => ({
  toRecogitoTextAnnotation: () => null,
}));

// The real annotator loads lazily and then drives its own timers, which call
// `requestAnimationFrame` after the test has finished — jsdom reports that as
// an unhandled exception and fails the whole run. The lightbox does not need
// the annotation engine, only the picture.
vi.mock("@recogito/text-annotator", () => ({
  createTextAnnotator: () => ({
    setAnnotations: () => undefined,
    on: () => undefined,
    destroy: () => undefined,
    scrollIntoView: () => undefined,
    rangeToSelector: () => null,
    getQuoteContext: () => ({ prefix: "", suffix: "" }),
  }),
}));

function dialog(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[role="dialog"]');
}

function toolbarPercent(): string | null {
  // `PreferenceButton` wraps each button in a tooltip span, so the percentage
  // is not the toolbar's first span - find it by the class that sizes the
  // readout.
  const readout = dialog()?.querySelector('[role="toolbar"] .tabular-nums');
  return readout?.textContent?.trim() ?? null;
}

async function clickToolbar(label: string) {
  const button = dialog()?.querySelector<HTMLButtonElement>(
    `button[aria-label="${label}"]`,
  );
  if (!button) throw new Error(`No "${label}" button in the lightbox`);
  await act(async () => {
    fireEvent.click(button);
  });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("reader image lightbox", () => {
  it("opens on a picture and closes again", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox
        src="/api/reading/materials/m1/media/image-01.jpg"
        alt="image-01.jpg"
        onClose={onClose}
      />,
    );
    expect(dialog()).not.toBeNull();
    await clickToolbar("Close");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("zooms in and out, and reports the percentage it is at", async () => {
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />,
    );
    expect(toolbarPercent()).toBe("100%");
    await clickToolbar("Zoom in");
    expect(toolbarPercent()).toBe("125%");
    await clickToolbar("Zoom in");
    expect(toolbarPercent()).toBe("156%");
    await clickToolbar("Zoom out");
    expect(toolbarPercent()).toBe("125%");
  });

  it("stops at the ends of the range instead of wrapping", async () => {
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />,
    );
    // Fit is the floor: the button is disabled rather than looping to 6x.
    expect(
      dialog()?.querySelector<HTMLButtonElement>(
        'button[aria-label="Zoom out"]',
      )?.disabled,
    ).toBe(true);
    for (let press = 0; press < 12; press += 1) await clickToolbar("Zoom in");
    expect(toolbarPercent()).toBe("600%");
    expect(
      dialog()?.querySelector<HTMLButtonElement>('button[aria-label="Zoom in"]')
        ?.disabled,
    ).toBe(true);
  });

  it("resets to fit from the toolbar", async () => {
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />,
    );
    await clickToolbar("Zoom in");
    expect(toolbarPercent()).toBe("125%");
    await clickToolbar("Fit");
    expect(toolbarPercent()).toBe("100%");
  });

  it("closes on Escape and on a click outside the picture", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={onClose} />,
    );
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    // A click that lands on the backdrop closes; one that lands on the picture
    // does not, or a drag to pan would dismiss the view it is panning.
    await act(async () => {
      fireEvent.click(dialog()!);
    });
    expect(onClose).toHaveBeenCalledTimes(2);
    await act(async () => {
      fireEvent.click(dialog()!.querySelector("img")!);
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("only pans once the picture is larger than the window", async () => {
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />,
    );
    const stage = dialog()!.querySelector("img")!.parentElement!;
    const transform = () =>
      (dialog()!.querySelector("img") as HTMLImageElement).style.transform;

    // At fit there is nothing to pan to, so a drag leaves the picture alone.
    await act(async () => {
      fireEvent.pointerDown(stage, { pointerId: 1, clientX: 10, clientY: 10 });
      fireEvent.pointerMove(stage, { pointerId: 1, clientX: 90, clientY: 40 });
      fireEvent.pointerUp(stage, { pointerId: 1 });
    });
    expect(transform()).toBe("translate(0px, 0px) scale(1)");

    await clickToolbar("Zoom in");
    await act(async () => {
      fireEvent.pointerDown(stage, { pointerId: 2, clientX: 10, clientY: 10 });
      fireEvent.pointerMove(stage, { pointerId: 2, clientX: 90, clientY: 40 });
      fireEvent.pointerUp(stage, { pointerId: 2 });
    });
    expect(transform()).toContain("translate(80px, 30px)");
  });
});

describe("opening a picture from the text reader", () => {
  it("opens a picture that is clicked, but not one inside a link", async () => {
    const view = render(
      <TextUnitView
        materialId="m1"
        unit="section"
        unitCount={3}
        annotations={[]}
        jump={null}
        onSelection={vi.fn()}
      />,
    );
    const root = view.container.firstElementChild as HTMLElement;

    // The reader's own media are API-backed, so put a picture in the DOM the
    // way the article would hold one.
    const figure = document.createElement("figure");
    const picture = document.createElement("img");
    picture.src = "/api/reading/materials/m1/media/image-01.jpg";
    picture.alt = "image-01.jpg";
    figure.appendChild(picture);
    root.appendChild(figure);

    await act(async () => {
      fireEvent.click(picture);
    });
    await waitFor(() => expect(dialog()).not.toBeNull());
    expect((dialog()!.querySelector("img") as HTMLImageElement).src).toContain(
      "image-01.jpg",
    );

    await clickToolbar("Close");
    expect(dialog()).toBeNull();

    // A picture that is a link's content belongs to the link, not the lightbox.
    const anchor = document.createElement("a");
    anchor.href = "https://example.com";
    const linked = document.createElement("img");
    linked.src = "/img.png";
    anchor.appendChild(linked);
    root.appendChild(anchor);
    await act(async () => {
      fireEvent.click(linked);
    });
    expect(dialog()).toBeNull();
  });

  it("does not open a picture when the click ended a text selection", async () => {
    const view = render(
      <TextUnitView
        materialId="m1"
        unit="section"
        unitCount={3}
        annotations={[]}
        jump={null}
        onSelection={vi.fn()}
      />,
    );
    const root = view.container.firstElementChild as HTMLElement;
    const picture = document.createElement("img");
    picture.src = "/img.png";
    root.appendChild(picture);

    // A drag that ends on a picture is a selection, not an "open this".
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.selectAllChildren(root);

    await act(async () => {
      fireEvent.click(picture);
    });
    expect(dialog()).toBeNull();
    selection?.removeAllRanges();
  });
});

describe("reader image lightbox keyboard and wheel", () => {
  // These paths had no test, and the CRAP report is what surfaced it: the
  // wheel handler and the +/-/0 shortcuts were unreached.
  it("zooms with the wheel, and never scrolls the page behind it", async () => {
    render(<ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />);
    const backdrop = dialog()!;
    await act(async () => {
      const wheel = new WheelEvent("wheel", {
        deltaY: -120,
        deltaMode: 0,
        bubbles: true,
        cancelable: true,
      });
      backdrop.dispatchEvent(wheel);
      expect(wheel.defaultPrevented).toBe(true);
    });
    expect(toolbarPercent()).not.toBe("100%");
  });

  it("zooms in, out and resets from the keyboard", async () => {
    render(<ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />);
    expect(toolbarPercent()).toBe("100%");

    await act(async () => {
      fireEvent.keyDown(window, { key: "+" });
    });
    expect(toolbarPercent()).toBe("125%");

    await act(async () => {
      fireEvent.keyDown(window, { key: "-" });
    });
    expect(toolbarPercent()).toBe("100%");

    await act(async () => {
      fireEvent.keyDown(window, { key: "+" });
      fireEvent.keyDown(window, { key: "+" });
    });
    await act(async () => {
      fireEvent.keyDown(window, { key: "0" });
    });
    expect(toolbarPercent()).toBe("100%");
  });

  it("leaves a shortcut with a modifier to the browser", async () => {
    render(<ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />);
    const before = toolbarPercent();
    await act(async () => {
      fireEvent.keyDown(window, { key: "+", metaKey: true });
    });
    // Cmd+plus is the browser's zoom, not ours.
    expect(toolbarPercent()).toBe(before);
  });
});

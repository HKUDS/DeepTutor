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

  it("clips a zoomed picture at the dialog, not at the picture's own box", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={onClose} />,
    );
    const stage = dialog()!.querySelector("img")!.parentElement as HTMLElement;

    // jsdom has no layout, so the geometry itself is the Lead's browser run;
    // what is asserted here is the structure that makes it true. The stage is
    // pinned to the fixed backdrop instead of being sized by the picture it
    // holds: `max-h-full max-w-full` shrank it to the unzoomed picture, so a
    // zoomed picture was clipped at its own box and panning could not reveal
    // the rest.
    expect(stage.className).toContain("absolute");
    expect(stage.className).toContain("inset-0");
    expect(stage.className).not.toContain("max-h-full");
    expect(stage.className).not.toContain("max-w-full");

    // The stage now covers the backdrop, so the empty area around the picture
    // is the stage; a click there still dismisses the way the backdrop's did.
    await act(async () => {
      fireEvent.click(stage);
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    // A drag that panned the picture ends with a click on that same stage, and
    // that click must not dismiss the view the drag was panning.
    await clickToolbar("Zoom in");
    await act(async () => {
      fireEvent.pointerDown(stage, { pointerId: 3, clientX: 10, clientY: 10 });
      fireEvent.pointerMove(stage, { pointerId: 3, clientX: 90, clientY: 40 });
      fireEvent.pointerUp(stage, { pointerId: 3 });
      fireEvent.click(stage);
    });
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

describe("a tap on the picture is not a click on the stage", () => {
  // jsdom does not retarget events, but Chromium does once the stage has
  // pointer capture: pointerdown IMG -> pointerup DIV(stage) -> click
  // DIV(stage). These cases dispatch that sequence by hand, because
  // `fireEvent.click(img)` alone would leave the target on the picture and
  // would never exercise the guard.
  function pictureAndStage() {
    const img = dialog()!.querySelector("img") as HTMLImageElement;
    return { img, stage: img.parentElement as HTMLElement };
  }

  it("does not dismiss a zoomed picture when capture retargets its click", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={onClose} />,
    );
    await clickToolbar("Zoom in");
    const { img, stage } = pictureAndStage();

    await act(async () => {
      // The native sequence the review reproduced: the gesture starts on the
      // picture, capture makes the browser report the release and the click on
      // the stage, and the stage is the dialog's "empty space" otherwise.
      fireEvent.pointerDown(img, { pointerId: 12, clientX: 100, clientY: 100 });
      fireEvent.pointerUp(stage, { pointerId: 12, clientX: 100, clientY: 100 });
      fireEvent.click(stage);
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("toggles the zoom on a double-click on the picture instead of closing", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={onClose} />,
    );
    const { img, stage } = pictureAndStage();

    // The first click of a double-click must not close the viewer, or there is
    // no second click to toggle with.
    await act(async () => {
      fireEvent.pointerDown(img, { pointerId: 21, clientX: 100, clientY: 100 });
      fireEvent.pointerUp(stage, { pointerId: 21, clientX: 100, clientY: 100 });
      fireEvent.click(stage);
      fireEvent.doubleClick(img);
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(toolbarPercent()).toBe("250%");

    // And while zoomed, a double-click restores 1x rather than exiting.
    await act(async () => {
      fireEvent.pointerDown(img, { pointerId: 22, clientX: 100, clientY: 100 });
      fireEvent.pointerUp(stage, { pointerId: 22, clientX: 100, clientY: 100 });
      fireEvent.click(stage);
      fireEvent.doubleClick(img);
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(toolbarPercent()).toBe("100%");
  });

  it("still dismisses on a click on genuinely empty stage space", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={onClose} />,
    );
    const { stage } = pictureAndStage();
    await act(async () => {
      fireEvent.pointerDown(stage, { pointerId: 31, clientX: 4, clientY: 4 });
      fireEvent.pointerUp(stage, { pointerId: 31, clientX: 4, clientY: 4 });
      fireEvent.click(stage);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not dismiss on the click that ends a pan", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={onClose} />,
    );
    await clickToolbar("Zoom in");
    const { img, stage } = pictureAndStage();
    await act(async () => {
      // A pan often starts on the picture, which at 2.5x fills most of the
      // stage; capture then reports the release and the click on the stage.
      fireEvent.pointerDown(img, { pointerId: 41, clientX: 10, clientY: 10 });
      fireEvent.pointerMove(stage, { pointerId: 41, clientX: 60, clientY: 40 });
      fireEvent.pointerUp(stage, { pointerId: 41, clientX: 60, clientY: 40 });
      fireEvent.click(stage);
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(
      (dialog()!.querySelector("img") as HTMLImageElement).style.transform,
    ).toContain("translate(50px, 30px)");
  });

  it("takes pointer capture only once the drag has travelled", async () => {
    const setPointerCapture = vi.fn();
    const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
    const original = Object.getOwnPropertyDescriptor(
      proto,
      "setPointerCapture",
    );
    Object.defineProperty(proto, "setPointerCapture", {
      configurable: true,
      writable: true,
      value: setPointerCapture,
    });
    try {
      render(
        <ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />,
      );
      await clickToolbar("Zoom in");
      const { img, stage } = pictureAndStage();

      await act(async () => {
        fireEvent.pointerDown(img, {
          pointerId: 51,
          clientX: 100,
          clientY: 100,
        });
      });
      // Capturing on pointerdown is what retargeted a tap on the picture.
      expect(setPointerCapture).not.toHaveBeenCalled();

      await act(async () => {
        fireEvent.pointerMove(stage, {
          pointerId: 51,
          clientX: 102,
          clientY: 101,
        });
      });
      // Jitter is still a click, not a pan.
      expect(setPointerCapture).not.toHaveBeenCalled();

      await act(async () => {
        fireEvent.pointerMove(stage, {
          pointerId: 51,
          clientX: 140,
          clientY: 100,
        });
      });
      expect(setPointerCapture).toHaveBeenCalledTimes(1);
      expect(setPointerCapture).toHaveBeenCalledWith(51);
    } finally {
      if (original) {
        Object.defineProperty(proto, "setPointerCapture", original);
      } else {
        delete proto.setPointerCapture;
      }
    }
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

describe("the lightbox traps Tab inside the dialog", () => {
  // `aria-modal` tells assistive technology the page behind is inert, but the
  // browser still tabs into it. jsdom does not perform Tab navigation either,
  // so a wrapped focus can only come from the component itself: this is the
  // focus trap, not the browser's default.
  function enabledControls(): HTMLButtonElement[] {
    return Array.from(
      dialog()!.querySelectorAll<HTMLButtonElement>("button:not([disabled])"),
    );
  }

  it("cycles through the toolbar instead of walking out into the reader", async () => {
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />,
    );

    const toolbarButtons = enabledControls();
    const first = toolbarButtons[0];
    const last = toolbarButtons[toolbarButtons.length - 1];
    // Zoom out is disabled at fit, so the ring starts at Zoom in and ends at
    // Close - the control a Tab press would otherwise leave from.
    expect(first).toBe(dialog()!.querySelector('button[aria-label="Zoom in"]'));
    expect(last).toBe(dialog()!.querySelector('button[aria-label="Close"]'));

    // Moving focus by hand blurs a toolbar button, and its tooltip reacts to
    // that, so the move itself belongs inside `act`.
    await act(async () => {
      last.focus();
    });
    expect(document.activeElement).toBe(last);
    await act(async () => {
      fireEvent.keyDown(last, { key: "Tab" });
    });
    expect(document.activeElement).toBe(first);

    await act(async () => {
      fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    });
    expect(document.activeElement).toBe(last);

    // Focus that ended up on the page behind the dialog is pulled back in by
    // the next Tab rather than continuing through the reader.
    const behind = document.createElement("button");
    behind.textContent = "reader control";
    document.body.appendChild(behind);
    await act(async () => {
      behind.focus();
    });
    expect(document.activeElement).toBe(behind);
    await act(async () => {
      fireEvent.keyDown(behind, { key: "Tab" });
    });
    expect(document.activeElement).toBe(first);
    expect(dialog()!.contains(document.activeElement)).toBe(true);
    behind.remove();

    // Focusing a toolbar button starts the lazily loaded tooltip layer; let it
    // settle inside the test instead of updating React after cleanup.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  });
});

describe("the toolbar band does not swallow a click on empty space", () => {
  it("lets a click beside the toolbar fall through to the dismissing stage", async () => {
    render(
      <ReaderImageLightbox src="/img.png" alt="diagram" onClose={vi.fn()} />,
    );
    const toolbar = dialog()!.querySelector('[role="toolbar"]')!;
    const band = toolbar.parentElement as HTMLElement;

    // jsdom does no hit testing, so this asserts the contract that makes
    // Chromium's hit test fall through: the band spans the window but is
    // transparent to the pointer, and only the toolbar inside it takes clicks.
    // Without it, the empty black strip either side of the toolbar - about
    // 34px tall - swallowed the click-to-dismiss the stage honours.
    expect(band.className).toContain("pointer-events-none");
    expect(toolbar.className).toContain("pointer-events-auto");
  });
});

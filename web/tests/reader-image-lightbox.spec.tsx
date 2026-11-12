import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TextUnitView } from "@/components/reading/TextUnitView";
import { collectLightboxImages } from "@/lib/reading-images";
import { ReaderImageLightbox } from "@/components/reading/ReaderImageLightbox";
import { EpubDocumentView } from "@/components/reading/EpubDocumentView";
import { allowsEpubPageTurn } from "@/lib/epub-page-turn";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

// The text reader loads its unit and its embedded-picture index over the API;
// this file only cares about the pictures already in the DOM. The EPUB reader
// also needs a position read and a save, and that save is what proves an arrow
// key did not turn a page behind the viewer.
const readingApi = vi.hoisted(() => ({
  saveReadingPosition: vi.fn(async () => undefined),
}));

vi.mock("@/lib/reading-api", () => ({
  getMaterialMedia: async () => [],
  getUnitText: async () => ({ text: "A paragraph.\n", eof: true }),
  materialMediaUrl: (materialId: string, name: string) =>
    `/api/reading/materials/${materialId}/media/${name}`,
  renderMaterialUrl: (materialId: string) =>
    `/api/reading/materials/${materialId}/render`,
  rawMaterialUrl: (materialId: string) =>
    `/api/reading/materials/${materialId}/raw`,
  getReadingPosition: async () => ({ locator: 1 }),
  saveReadingPosition: readingApi.saveReadingPosition,
}));

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(async () => ({
    ok: true,
    arrayBuffer: async () => new ArrayBuffer(8),
  })),
}));

// A rendition whose page turns are observable, so "the chapter moved behind the
// viewer" is a call count rather than an inference from the DOM.
const epub = vi.hoisted(() => {
  const rendition = {
    display: vi.fn(async () => undefined),
    currentLocation: vi.fn(() => ({ start: { cfi: "epubcfi(/6/2)" } })),
    next: vi.fn(async () => undefined),
    prev: vi.fn(async () => undefined),
    resize: vi.fn(),
    spread: vi.fn(),
    destroy: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    annotations: { highlight: vi.fn(), remove: vi.fn() },
    hooks: { content: { register: vi.fn() } },
    themes: {
      registerCss: vi.fn(),
      select: vi.fn(),
      fontSize: vi.fn(),
      override: vi.fn(),
    },
  };
  return {
    rendition,
    locations: {
      generate: vi.fn(async () => []),
      percentageFromCfi: vi.fn((): number | null => null),
    },
    renderTo: vi.fn(() => rendition),
  };
});

vi.mock("epubjs", () => ({
  default: () => ({
    open: async () => undefined,
    ready: Promise.resolve(),
    renderTo: epub.renderTo,
    spine: { get: () => ({ href: "one.xhtml" }) },
    locations: epub.locations,
    destroy: vi.fn(),
  }),
}));

vi.mock("@/lib/reading-outline", () => ({
  activeReaderHeading: () => null,
  extractReaderHeadings: () => [],
  extractEpubHeadings: () => [],
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
        images={[
          { src: "/api/reading/materials/m1/media/image-01.jpg", alt: "image-01.jpg" },
        ]}
        index={0}
        onIndexChange={() => {}}
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={onClose} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />,
    );
    await clickToolbar("Zoom in");
    expect(toolbarPercent()).toBe("125%");
    await clickToolbar("Fit");
    expect(toolbarPercent()).toBe("100%");
  });

  it("closes on Escape and on a click outside the picture", async () => {
    const onClose = vi.fn();
    render(
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={onClose} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={onClose} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={onClose} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={onClose} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={onClose} />,
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
        <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />,
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
    // The element the reader scopes its picture collection to — `data-reader-unit`,
    // not the outermost wrapper. Appending to the wrapper put the picture
    // outside the scope, which the collector now refuses (a click from the
    // portal must not be read as a click on the page).
    const root = view.container.querySelector<HTMLElement>("[data-reader-unit]")!;

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
    render(<ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />);
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
    render(<ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />);
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
    render(<ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />);
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />,
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
      <ReaderImageLightbox images={[{ src: "/img.png", alt: "diagram" }]} index={0} onIndexChange={() => {}} onClose={vi.fn()} />,
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

describe("the EPUB reader while the picture viewer is open", () => {
  // The viewer is portaled to `document.body`, so it is no descendant of the
  // EPUB reader's own container: nothing on the reader's side can tell that it
  // is up. These cases drive the real `window` keydown listener the reader
  // installs, with the focus the viewer really gives the dialog, and watch the
  // rendition: a page turn there is the defect.
  async function mountEpub() {
    render(
      <EpubDocumentView
        materialId="book"
        unitCount={1}
        unitRefs={[{ locator: 1, source_href: "one.xhtml", title: "One" }]}
        annotations={[]}
        jump={null}
        onSelection={() => undefined}
      />,
    );
    await waitFor(() => expect(epub.renderTo).toHaveBeenCalled());
    const install = epub.rendition.hooks.content.register.mock
      .calls[0]?.[0] as unknown as (contents: {
      document: Document;
      window: Window;
    }) => void;
    expect(install).toBeTypeOf("function");
    // epub.js hands each rendered section to this hook; the section is its own
    // document, which is where the picture click listener is installed.
    const chapter = document.implementation.createHTMLDocument("chapter");
    await act(async () => {
      install({ document: chapter, window });
    });
    return chapter;
  }

  async function openViewerOn(chapter: Document, src: string) {
    const picture = chapter.createElement("img");
    if (src) picture.setAttribute("src", src);
    picture.alt = "diagram";
    chapter.body.appendChild(picture);
    await act(async () => {
      picture.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    return picture;
  }

  it("turns no page when an arrow key is pressed in the viewer", async () => {
    const chapter = await mountEpub();
    await openViewerOn(chapter, "/img.png");
    await waitFor(() => expect(dialog()).not.toBeNull());

    // The premise of the defect: focus starts on the backdrop, a `div` that
    // matches nothing the page-turn guard used to treat as interactive.
    const backdrop = dialog()!;
    expect(document.activeElement).toBe(backdrop);
    expect(allowsEpubPageTurn(backdrop)).toBe(false);

    await act(async () => {
      fireEvent.keyDown(backdrop, { key: "ArrowRight" });
      fireEvent.keyDown(backdrop, { key: "ArrowLeft" });
    });
    expect(epub.rendition.next).not.toHaveBeenCalled();
    expect(epub.rendition.prev).not.toHaveBeenCalled();

    // And with no page turn there is no relocation, so no reading position is
    // written behind the viewer either. The save from the book's own initial
    // relocation is settled first, so what is counted here is the keypress.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    readingApi.saveReadingPosition.mockClear();
    await act(async () => {
      fireEvent.keyDown(backdrop, { key: "ArrowRight" });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(readingApi.saveReadingPosition).not.toHaveBeenCalled();
  });

  it("turns no page when the arrow key lands on a control inside the viewer", async () => {
    const chapter = await mountEpub();
    await openViewerOn(chapter, "/img.png");
    await waitFor(() => expect(dialog()).not.toBeNull());

    // The picture itself and the stage around it are not interactive elements,
    // so they are the places inside the viewer where the old guard passed. The
    // stage receives focus here the way a click on the picture leaves it.
    const stage = dialog()!.querySelector("img")!.parentElement as HTMLElement;
    await act(async () => {
      stage.focus();
      fireEvent.keyDown(stage, { key: "ArrowRight" });
    });
    expect(epub.rendition.next).not.toHaveBeenCalled();

    const picture = dialog()!.querySelector("img")!;
    await act(async () => {
      fireEvent.keyDown(picture, { key: "ArrowLeft" });
    });
    expect(epub.rendition.prev).not.toHaveBeenCalled();

    // Escape and the Tab trap the viewer already owns still work with the
    // page-turn guard in place.
    const first = dialog()!.querySelector<HTMLButtonElement>(
      'button[aria-label="Zoom in"]',
    )!;
    const close = dialog()!.querySelector<HTMLButtonElement>(
      'button[aria-label="Close"]',
    )!;
    await act(async () => {
      close.focus();
      fireEvent.keyDown(close, { key: "Tab" });
    });
    expect(document.activeElement).toBe(first);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  });

  it("does not open the viewer for a picture with no source", async () => {
    const chapter = await mountEpub();
    // A picture that never resolved: the click used to hand `""` to the
    // viewer, which then drew an empty full-screen overlay.
    await openViewerOn(chapter, "");
    expect(dialog()).toBeNull();

    // The same section still opens a picture that has a source, so the guard
    // is a source check and not a broken click path.
    await openViewerOn(chapter, "/img.png");
    await waitFor(() => expect(dialog()).not.toBeNull());
    expect((dialog()!.querySelector("img") as HTMLImageElement).src).toContain(
      "/img.png",
    );
  });
});

/**
 * Stepping between the pictures of one unit.
 *
 * The viewer took a single image until the reader could hand it the list, so
 * these cases are new with the list. What they pin is the state rule: zoom and
 * pan belong to the picture on screen, not to the viewer, so every step drops
 * them — carrying a 6x zoom across would show the next picture cropped and
 * off-centre, which reads as a broken image.
 */
describe("stepping between pictures", () => {
  const gallery = [
    { src: "/one.png", alt: "first" },
    { src: "/two.png", alt: "second" },
    { src: "/three.png", alt: "third" },
  ];

  function open(index: number, onIndexChange = vi.fn()) {
    const view = render(
      <ReaderImageLightbox
        images={gallery}
        index={index}
        onIndexChange={onIndexChange}
        onClose={vi.fn()}
      />,
    );
    return { ...view, onIndexChange };
  }

  const shown = (view: ReturnType<typeof render>) =>
    view.getByRole("dialog").querySelector("img")?.getAttribute("src");

  it("shows the picture at the given index", () => {
    const view = open(1);
    expect(shown(view)).toBe("/two.png");
  });

  it("reports the next and previous index from the arrow keys", async () => {
    const view = open(1);
    await act(async () => {
      fireEvent.keyDown(window, { key: "ArrowRight" });
    });
    expect(view.onIndexChange).toHaveBeenLastCalledWith(2);
    await act(async () => {
      fireEvent.keyDown(window, { key: "ArrowLeft" });
    });
    expect(view.onIndexChange).toHaveBeenLastCalledWith(0);
  });

  it("does not wrap at the ends", async () => {
    // Disabled rather than wrapping: the reader can see where the list ends,
    // and a wrap makes "left" mean two different things.
    const first = open(0);
    await act(async () => {
      fireEvent.keyDown(window, { key: "ArrowLeft" });
    });
    expect(first.onIndexChange).not.toHaveBeenCalled();
    first.unmount();

    const last = open(2);
    await act(async () => {
      fireEvent.keyDown(window, { key: "ArrowRight" });
    });
    expect(last.onIndexChange).not.toHaveBeenCalled();
  });

  it("drops the zoom when the picture changes", async () => {
    const onIndexChange = vi.fn();
    const view = render(
      <ReaderImageLightbox
        images={gallery}
        index={0}
        onIndexChange={onIndexChange}
        onClose={vi.fn()}
      />,
    );
    // Zoom in twice, so the percentage is clearly off 100.
    const zoomIn = view.getByRole("button", { name: "Zoom in" });
    await act(async () => {
      fireEvent.click(zoomIn);
      fireEvent.click(zoomIn);
    });
    expect(view.getByRole("dialog").textContent).not.toContain("100%");

    // Stepping reports the new index; the caller re-renders with it, which is
    // what resets the view.
    await act(async () => {
      fireEvent.keyDown(window, { key: "ArrowRight" });
    });
    expect(onIndexChange).toHaveBeenCalledWith(1);
    view.rerender(
      <ReaderImageLightbox
        images={gallery}
        index={1}
        onIndexChange={onIndexChange}
        onClose={vi.fn()}
      />,
    );
    expect(view.getByRole("dialog").textContent).toContain("100%");
  });

  it("replaces the image node on a step, so the old picture cannot linger", () => {
    // React keeps one `<img>` and only rewrites `src`; a browser goes on
    // painting the OLD picture until the new one decodes, so a reader pressing
    // Right on a large scan saw the same image and pressed again. A keyed node
    // forces a fresh element, which has nothing to paint yet.
    const onIndexChange = vi.fn();
    const view = render(
      <ReaderImageLightbox
        images={gallery}
        index={0}
        onIndexChange={onIndexChange}
        onClose={vi.fn()}
      />,
    );
    const before = view.getByRole("dialog").querySelector("img");
    expect(before?.getAttribute("src")).toBe("/one.png");

    view.rerender(
      <ReaderImageLightbox
        images={gallery}
        index={1}
        onIndexChange={onIndexChange}
        onClose={vi.fn()}
      />,
    );
    const after = view.getByRole("dialog").querySelector("img");
    expect(after?.getAttribute("src")).toBe("/two.png");
    // A different element, not the same one with a new attribute.
    expect(after).not.toBe(before);
  });

  it("offers no navigation when there is only one picture", () => {
    const view = render(
      <ReaderImageLightbox
        images={[{ src: "/only.png", alt: "only" }]}
        index={0}
        onIndexChange={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(view.queryByRole("button", { name: "Next image" })).toBeNull();
    expect(view.queryByRole("button", { name: "Previous image" })).toBeNull();
  });

  it("names the position in the toolbar", () => {
    const view = open(1);
    expect(view.getByRole("dialog").textContent).toContain("2 / 3");
  });
});

/**
 * The collector, against the real DOM shape a reader produces.
 *
 * The stepping cases above feed a hand-written list; these build a container the
 * way the article does and let the collector decide — which is where the
 * duplicate-`src` defect lived.
 */
describe("collecting the pictures of a unit", () => {
  function container(entries: Array<{ src: string; linked?: boolean }>) {
    const root = document.createElement("div");
    for (const entry of entries) {
      const image = document.createElement("img");
      image.src = entry.src;
      image.alt = entry.src;
      if (entry.linked) {
        const anchor = document.createElement("a");
        anchor.href = "https://example.com";
        anchor.appendChild(image);
        root.appendChild(anchor);
      } else {
        root.appendChild(image);
      }
    }
    return root;
  }

  it("takes the index from the clicked node, not from its source", () => {
    // Two entries with the same source are different pictures; looking the index
    // up by `src` returned the first one every time.
    const root = container([
      { src: "/same.png" },
      { src: "/same.png" },
      { src: "/other.png" },
    ]);
    const second = root.querySelectorAll("img")[1] as HTMLImageElement;
    const { images, index } = collectLightboxImages(root, second);
    expect(images).toHaveLength(3);
    expect(index).toBe(1);
  });

  it("indexes the filtered list when an earlier image has no source", () => {
    const root = document.createElement("div");
    const missing = document.createElement("img");
    const first = document.createElement("img");
    const second = document.createElement("img");
    first.src = "/first.png";
    second.src = "/second.png";
    root.append(missing, first, second);

    const selected = collectLightboxImages(root, first);
    expect(selected.images.map((entry) => entry.src)).toEqual([
      "/first.png",
      "/second.png",
    ]);
    expect(selected.index).toBe(0);

    expect(collectLightboxImages(root, second).index).toBe(1);
  });

  it("skips pictures that belong to a link", () => {
    const root = container([
      { src: "/linked.png", linked: true },
      { src: "/plain.png" },
    ]);
    const plain = root.querySelectorAll("img")[1] as HTMLImageElement;
    const { images, index } = collectLightboxImages(root, plain);
    expect(images.map((entry) => entry.src)).toEqual(["/plain.png"]);
    expect(index).toBe(0);
  });

  it("falls back to the clicked picture when the scope holds none", () => {
    const root = document.createElement("div");
    const loose = document.createElement("img");
    loose.src = "/loose.png";
    const { images, index } = collectLightboxImages(root, loose);
    expect(images).toEqual([{ src: "/loose.png", alt: "" }]);
    expect(index).toBe(0);
  });
});

/**
 * The viewer is a React descendant of the reader, not a DOM one.
 *
 * Its clicks bubble through the React tree, so the reader's capture handler saw
 * them as clicks on the page: it rebuilt the list from the page and reset the
 * index (with duplicates the counter jumped from 3/3 to 1/3) and called
 * `preventDefault` on the viewer's own click.
 */
describe("pointer events inside the portaled viewer keep focus inside it", () => {
  it("does not refocus the text reader behind the viewer", async () => {
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
    const unit = view.container.querySelector<HTMLElement>("[data-reader-unit]")!;
    const picture = document.createElement("img");
    picture.src = "/img.png";
    unit.appendChild(picture);
    await act(async () => {
      fireEvent.click(picture);
    });
    const overlay = await waitFor(() => {
      const node = document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]');
      if (!node) throw new Error("no lightbox");
      return node;
    });
    expect(overlay.contains(document.activeElement)).toBe(true);

    // React portal events bubble through the component tree, even when the
    // overlay is outside the reader's DOM. This used to focus the reader root.
    await act(async () => {
      fireEvent.pointerDown(overlay.querySelector("img")!);
    });
    expect(overlay.contains(document.activeElement)).toBe(true);
  });
});

describe("clicks inside the viewer are not page clicks", () => {
  it("leaves the list and the index alone", async () => {
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
    const root = view.container.querySelector<HTMLElement>("[data-reader-unit]")!;
    for (const name of ["a.png", "b.png"]) {
      const image = document.createElement("img");
      image.src = `/api/reading/materials/m1/media/${name}`;
      image.alt = name;
      root.appendChild(image);
    }

    await act(async () => {
      fireEvent.click(root.querySelectorAll("img")[1] as HTMLImageElement);
    });
    const dialog = await waitFor(() => {
      const found = document.querySelector('[role="dialog"]');
      if (!found) throw new Error("no viewer yet");
      return found as HTMLElement;
    });
    expect(dialog.textContent).toContain("2 / 2");

    // Click the picture INSIDE the viewer. Nothing about the list may change.
    const inside = dialog.querySelector("img") as HTMLImageElement;
    await act(async () => {
      fireEvent.click(inside);
    });
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
      "2 / 2",
    );
  });
});

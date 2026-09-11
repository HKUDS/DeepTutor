"use client";

import { useEffect, useState } from "react";

/**
 * Tracks the ``data-picker-open`` marker ``PickerShell`` puts on ``<body>``
 * while a fullscreen picker or modal is up.
 *
 * CSS-driven ambient animations freeze themselves through that attribute
 * (``animation-play-state: paused`` in globals.css) because their repaints
 * were being re-sampled by the scrim's ``backdrop-filter`` and read as a
 * constant shimmer behind it. A canvas paints from its own rAF loop, which
 * no stylesheet can reach — so canvas-backed indicators have to read the
 * flag and pause themselves.
 */
export function usePickerOpen(): boolean {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const read = () => setOpen(document.body.hasAttribute("data-picker-open"));
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-picker-open"],
    });
    return () => observer.disconnect();
  }, []);

  return open;
}

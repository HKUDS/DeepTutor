export interface DownloadElementPdfOptions {
  filename: string;
  title?: string;
}

function normalizeFilename(filename: string): string {
  const cleaned = filename
    .trim()
    .replace(/[\\/:*?"<>|\n\r\t]/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 80);
  return cleaned.endsWith(".pdf")
    ? cleaned
    : `${cleaned || "deeptutor-export"}.pdf`;
}

function prepareExportNode(source: HTMLElement, title?: string): HTMLElement {
  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style.left = "-10000px";
  container.style.top = "0";
  container.style.width = "794px";
  container.style.minHeight = "1123px";
  container.style.boxSizing = "border-box";
  container.style.padding = "56px";
  container.style.background = "#ffffff";
  container.style.color = "#111827";
  container.style.fontFamily =
    'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif';
  container.style.fontSize = "16px";
  container.style.lineHeight = "1.65";
  container.style.setProperty("--background", "#ffffff");
  container.style.setProperty("--foreground", "#111827");
  container.style.setProperty("--muted", "#f3f4f6");
  container.style.setProperty("--muted-foreground", "#4b5563");
  container.style.setProperty("--border", "#d1d5db");
  container.style.setProperty("--card", "#ffffff");
  container.style.setProperty("--popover", "#ffffff");
  container.style.setProperty("--primary", "#111827");
  container.style.setProperty("--primary-foreground", "#ffffff");

  if (title?.trim()) {
    const heading = document.createElement("h1");
    heading.textContent = title.trim();
    heading.style.margin = "0 0 24px";
    heading.style.fontSize = "28px";
    heading.style.lineHeight = "1.25";
    heading.style.fontWeight = "700";
    container.appendChild(heading);
  }

  const clone = source.cloneNode(true) as HTMLElement;
  clone.style.maxHeight = "none";
  clone.style.overflow = "visible";
  clone.style.width = "100%";
  container.appendChild(clone);
  document.body.appendChild(container);
  return container;
}

function canvasSlice(
  source: HTMLCanvasElement,
  y: number,
  height: number,
): HTMLCanvasElement {
  const slice = document.createElement("canvas");
  slice.width = source.width;
  slice.height = height;
  const ctx = slice.getContext("2d");
  if (!ctx) throw new Error("Unable to create PDF canvas context.");
  ctx.drawImage(
    source,
    0,
    y,
    source.width,
    height,
    0,
    0,
    source.width,
    height,
  );
  return slice;
}

export async function downloadElementAsPdf(
  source: HTMLElement,
  options: DownloadElementPdfOptions,
): Promise<void> {
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
    import("html2canvas"),
    import("jspdf"),
  ]);

  const exportNode = prepareExportNode(source, options.title);
  try {
    if (document.fonts?.ready) {
      await document.fonts.ready;
    }
    const canvas = await html2canvas(exportNode, {
      backgroundColor: "#ffffff",
      scale: Math.min(window.devicePixelRatio || 1, 2),
      useCORS: true,
      logging: false,
      windowWidth: exportNode.scrollWidth,
      windowHeight: exportNode.scrollHeight,
    });

    const pdf = new jsPDF({ unit: "pt", format: "a4", orientation: "portrait" });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const margin = 36;
    const contentWidth = pageWidth - margin * 2;
    const contentHeight = pageHeight - margin * 2;
    const ratio = contentWidth / canvas.width;
    const sliceHeight = Math.max(1, Math.floor(contentHeight / ratio));

    for (let y = 0, page = 0; y < canvas.height; y += sliceHeight, page += 1) {
      if (page > 0) pdf.addPage();
      const height = Math.min(sliceHeight, canvas.height - y);
      const slice = canvasSlice(canvas, y, height);
      const image = slice.toDataURL("image/png");
      pdf.addImage(image, "PNG", margin, margin, contentWidth, height * ratio);
    }

    pdf.save(normalizeFilename(options.filename));
  } finally {
    exportNode.remove();
  }
}

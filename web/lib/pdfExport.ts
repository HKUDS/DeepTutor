/**
 * PDF Export Utility for Research Reports
 *
 * This module handles the conversion of HTML content to PDF with proper:
 * - Page margins and spacing
 * - SVG to image conversion (for Mermaid diagrams)
 * - Correct page splitting without content overlap
 * - Page numbering
 */

import jsPDF from "jspdf";
import html2canvas from "html2canvas";

export interface PdfExportOptions {
  /** Filename for the PDF (without .pdf extension) */
  filename?: string;
  /** Left margin in mm */
  marginLeft?: number;
  /** Right margin in mm */
  marginRight?: number;
  /** Top margin in mm */
  marginTop?: number;
  /** Bottom margin in mm */
  marginBottom?: number;
  /** Whether to show page numbers */
  showPageNumbers?: boolean;
  /** Scale factor for rendering (higher = better quality but slower) */
  scale?: number;
}

const defaultOptions: Required<PdfExportOptions> = {
  filename: "report",
  marginLeft: 20,
  marginRight: 20,
  marginTop: 25,
  marginBottom: 25,
  showPageNumbers: true,
  scale: 2,
};

/**
 * Convert all SVG elements in an element to PNG images
 * This is necessary because html2canvas has limited SVG support
 */
async function convertSvgsToImages(element: HTMLElement): Promise<void> {
  const svgs = element.querySelectorAll("svg");

  const conversionPromises = Array.from(svgs).map(async (svg) => {
    try {
      const bbox = svg.getBoundingClientRect();
      const width = Math.max(bbox.width, 100);
      const height = Math.max(bbox.height, 100);

      // Clone and set explicit dimensions
      const clonedSvg = svg.cloneNode(true) as SVGElement;
      clonedSvg.setAttribute("width", String(width));
      clonedSvg.setAttribute("height", String(height));
      clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");

      // Serialize to string
      const serializer = new XMLSerializer();
      let svgString = serializer.serializeToString(clonedSvg);

      // Ensure proper XML encoding
      if (!svgString.includes("xmlns=")) {
        svgString = svgString.replace(
          "<svg",
          '<svg xmlns="http://www.w3.org/2000/svg"',
        );
      }

      // Create blob and URL
      const svgBlob = new Blob([svgString], {
        type: "image/svg+xml;charset=utf-8",
      });
      const url = URL.createObjectURL(svgBlob);

      // Load as image
      const img = new Image();

      await new Promise<void>((resolve) => {
        img.onload = () => {
          // Create high-res canvas
          const canvas = document.createElement("canvas");
          const scale = 2;
          canvas.width = width * scale;
          canvas.height = height * scale;

          const ctx = canvas.getContext("2d");
          if (ctx) {
            ctx.fillStyle = "white";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.scale(scale, scale);
            ctx.drawImage(img, 0, 0, width, height);

            // Create replacement image element
            const replacement = document.createElement("img");
            replacement.src = canvas.toDataURL("image/png");
            replacement.style.width = `${width}px`;
            replacement.style.height = `${height}px`;
            replacement.style.display = "block";
            replacement.style.margin = "16px auto";

            svg.parentNode?.replaceChild(replacement, svg);
          }
          URL.revokeObjectURL(url);
          resolve();
        };

        img.onerror = () => {
          URL.revokeObjectURL(url);
          // Don't reject, just log and continue
          console.warn("Failed to convert SVG, skipping");
          resolve();
        };
      });

      img.src = url;
    } catch (err) {
      console.warn("SVG conversion error:", err);
    }
  });

  await Promise.all(conversionPromises);
}

/**
 * Split a tall canvas into page-sized chunks
 */
function splitCanvasIntoPages(
  canvas: HTMLCanvasElement,
  pageWidth: number,
  pageHeight: number,
  marginLeft: number,
  marginTop: number,
  marginBottom: number,
): HTMLCanvasElement[] {
  const contentWidth = pageWidth - marginLeft * 2;
  const contentHeight = pageHeight - marginTop - marginBottom;

  // Calculate dimensions in canvas pixels
  const imgWidth = contentWidth;
  // Convert content height to image pixels
  const pageHeightInImgPixels = (contentHeight / imgWidth) * canvas.width;

  const numPages = Math.ceil(canvas.height / pageHeightInImgPixels);
  const pages: HTMLCanvasElement[] = [];

  for (let i = 0; i < numPages; i++) {
    const pageCanvas = document.createElement("canvas");
    pageCanvas.width = canvas.width;
    pageCanvas.height = Math.min(
      pageHeightInImgPixels,
      canvas.height - i * pageHeightInImgPixels,
    );

    const ctx = pageCanvas.getContext("2d");
    if (ctx) {
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, pageCanvas.width, pageCanvas.height);

      // Draw the portion of the original canvas for this page
      ctx.drawImage(
        canvas,
        0,
        i * pageHeightInImgPixels, // Source x, y
        canvas.width,
        pageCanvas.height, // Source width, height
        0,
        0, // Destination x, y
        canvas.width,
        pageCanvas.height, // Destination width, height
      );
    }

    pages.push(pageCanvas);
  }

  return pages;
}

/**
 * Export HTML element to PDF
 */
export async function exportToPdf(
  element: HTMLElement,
  options: PdfExportOptions = {},
): Promise<void> {
  const opts = { ...defaultOptions, ...options };

  // Clone element to avoid modifying the original
  const clone = element.cloneNode(true) as HTMLElement;
  clone.style.position = "absolute";
  clone.style.top = "-99999px";
  clone.style.left = "-99999px";
  clone.style.width = "800px";
  clone.style.backgroundColor = "white";
  document.body.appendChild(clone);

  try {
    // Wait for any async rendering
    await new Promise((resolve) => setTimeout(resolve, 500));

    // Convert SVGs to images
    await convertSvgsToImages(clone);

    // Additional wait for image loading
    await new Promise((resolve) => setTimeout(resolve, 300));

    // Capture as canvas
    const canvas = await html2canvas(clone, {
      scale: opts.scale,
      useCORS: true,
      logging: false,
      backgroundColor: "#ffffff",
      windowWidth: 800,
      allowTaint: true,
    });

    // PDF dimensions
    const pageWidth = 210; // A4 width in mm
    const pageHeight = 297; // A4 height in mm

    // Split canvas into pages
    const pages = splitCanvasIntoPages(
      canvas,
      pageWidth,
      pageHeight,
      opts.marginLeft,
      opts.marginTop,
      opts.marginBottom,
    );

    // Create PDF
    const pdf = new jsPDF("p", "mm", "a4");
    const contentWidth = pageWidth - opts.marginLeft - opts.marginRight;
    const contentHeight = pageHeight - opts.marginTop - opts.marginBottom;

    for (let i = 0; i < pages.length; i++) {
      if (i > 0) {
        pdf.addPage();
      }

      const pageCanvas = pages[i];
      const imgData = pageCanvas.toDataURL("image/png");

      // Calculate height for this page's content
      const imgHeight = (pageCanvas.height * contentWidth) / pageCanvas.width;

      // Add image to PDF
      pdf.addImage(
        imgData,
        "PNG",
        opts.marginLeft,
        opts.marginTop,
        contentWidth,
        Math.min(imgHeight, contentHeight),
      );

      // Add page number
      if (opts.showPageNumbers) {
        pdf.setFontSize(10);
        pdf.setTextColor(128, 128, 128);
        pdf.text(`${i + 1} / ${pages.length}`, pageWidth / 2, pageHeight - 10, {
          align: "center",
        });
      }
    }

    // Save PDF
    pdf.save(`${opts.filename}.pdf`);
  } finally {
    // Clean up
    document.body.removeChild(clone);
  }
}

/**
 * Preprocess markdown content for PDF export
 * - Expands <details> tags
 * - Cleans up formatting
 */
export function preprocessMarkdownForPdf(markdown: string): string {
  if (!markdown) return markdown;

  let result = markdown;

  // Remove <details> and </details> tags
  result = result.replace(/<details\s*>/gi, "");
  result = result.replace(/<\/details\s*>/gi, "");

  // Convert <summary>...</summary> to bold headers
  result = result.replace(
    /<summary\s*>([^<]*)<\/summary\s*>/gi,
    "\n\n**$1**\n",
  );

  // Remove empty anchor tags
  result = result.replace(/<a\s+id="[^"]*"\s*><\/a>/gi, "");

  // Clean up excessive newlines
  result = result.replace(/\n{4,}/g, "\n\n\n");

  return result;
}

export default exportToPdf;

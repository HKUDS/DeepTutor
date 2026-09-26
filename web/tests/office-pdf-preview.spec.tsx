import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import OfficePdfPreview from "@/components/chat/preview/previewers/OfficePdfPreview";

const fixture = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({ apiFetch: fixture.apiFetch }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/chat/preview/previewers/PdfPreview", () => ({
  default: ({ url, filename }: { url: string; filename: string }) => (
    <div data-testid="pdf-preview" data-url={url}>
      {filename}
    </div>
  ),
}));

const originalCreateObjectURL = Object.getOwnPropertyDescriptor(
  URL,
  "createObjectURL",
);
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(
  URL,
  "revokeObjectURL",
);
const createObjectURL = vi.fn(() => "blob:http://localhost/converted.pdf");
const revokeObjectURL = vi.fn();

function conversionResponse({
  ok = true,
  contentType = "application/pdf",
  body = new Blob(["%PDF-1.4"], { type: "application/pdf" }),
}: {
  ok?: boolean;
  contentType?: string;
  body?: Blob;
} = {}): Response {
  return {
    ok,
    headers: { get: (name: string) => (name === "content-type" ? contentType : null) },
    blob: async () => body,
  } as Response;
}

function restoreUrlMethod(name: "createObjectURL" | "revokeObjectURL", descriptor?: PropertyDescriptor) {
  if (descriptor) Object.defineProperty(URL, name, descriptor);
  else Reflect.deleteProperty(URL, name);
}

beforeEach(() => {
  window.history.replaceState({}, "", "/chat?dt_workspace=active-workspace");
  fixture.apiFetch.mockReset();
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeObjectURL,
  });
});

afterEach(() => {
  restoreUrlMethod("createObjectURL", originalCreateObjectURL);
  restoreUrlMethod("revokeObjectURL", originalRevokeObjectURL);
  window.history.replaceState({}, "", "/");
});

it("requests a served Office file by local URL in its source workspace and shows the converted PDF", async () => {
  fixture.apiFetch.mockResolvedValue(conversionResponse());
  const source =
    "/files/workspace-items/item-1/report.docx?dt_workspace=source-workspace";
  const view = render(
    <OfficePdfPreview
      url={source}
      filename="report.docx"
      fallback={<div>Original preview</div>}
    />,
  );

  expect(await screen.findByTestId("pdf-preview")).toHaveAttribute(
    "data-url",
    "blob:http://localhost/converted.pdf",
  );
  expect(screen.queryByText("Original preview")).not.toBeInTheDocument();
  const [endpoint, options] = fixture.apiFetch.mock.calls[0] as [string, RequestInit];
  const requestUrl = new URL(endpoint, window.location.origin);
  expect(requestUrl.pathname).toBe("/api/file-preview/pdf");
  expect(requestUrl.searchParams.get("source")).toBe(source);
  expect(requestUrl.searchParams.get("dt_workspace")).toBe("source-workspace");
  expect(options).toEqual(
    expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
  );
  expect(options.method).toBeUndefined();
  expect(fixture.apiFetch).toHaveBeenCalledTimes(1);

  view.unmount();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:http://localhost/converted.pdf");
});

it.each([
  [
    "data URL",
    "data:application/vnd.openxmlformats-officedocument.presentationml.presentation;base64,UEs=",
  ],
  ["blob URL", "blob:http://localhost/source.pptx"],
])("uploads an unsaved %s as a named Office file before showing the PDF", async (_kind, source) => {
  const officeBlob = new Blob(["office bytes"], {
    type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  });
  fixture.apiFetch.mockResolvedValueOnce({
    ok: true,
    blob: async () => officeBlob,
  } as Response).mockResolvedValueOnce(conversionResponse());

  render(
    <OfficePdfPreview
      url={source}
      filename="slides.pptx"
      fallback={<div>Original preview</div>}
    />,
  );

  expect(await screen.findByTestId("pdf-preview")).toHaveTextContent("slides.pptx");
  expect(fixture.apiFetch).toHaveBeenCalledWith(source, {
    signal: expect.any(AbortSignal),
  });
  const [endpoint, options] = fixture.apiFetch.mock.calls[1] as [string, RequestInit];
  const requestUrl = new URL(endpoint, window.location.origin);
  expect(requestUrl.pathname).toBe("/api/file-preview/pdf");
  expect(requestUrl.searchParams.get("dt_workspace")).toBe("active-workspace");
  expect(requestUrl.searchParams.has("source")).toBe(false);
  expect(options.method).toBe("POST");
  expect(options.signal).toEqual(expect.any(AbortSignal));
  const file = (options.body as FormData).get("file") as File;
  expect(file.name).toBe("slides.pptx");
  expect(file.size).toBe(officeBlob.size);
  expect(file.type).toBe(officeBlob.type);
});

it("keeps the original renderer when PDF conversion fails", async () => {
  fixture.apiFetch.mockResolvedValue(conversionResponse({ ok: false }));

  render(
    <OfficePdfPreview
      url="/files/outputs/slides.pptx"
      filename="slides.pptx"
      fallback={<div>Original preview</div>}
    />,
  );

  expect(await screen.findByText("Original preview")).toBeInTheDocument();
  expect(screen.queryByTestId("pdf-preview")).not.toBeInTheDocument();
  expect(createObjectURL).not.toHaveBeenCalled();
});

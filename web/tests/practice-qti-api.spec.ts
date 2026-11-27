import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api";
import { exportQtiPackage, PracticeRequestError } from "@/lib/practice-api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));

const createObjectURL = vi.fn(() => "blob:qti-export");
const revokeObjectURL = vi.fn();

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  createObjectURL.mockReturnValue("blob:qti-export");
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = createObjectURL;
    static revokeObjectURL = revokeObjectURL;
  });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("POSTs selected entry IDs as a QTI 3.0 ZIP and downloads and revokes the response blob", async () => {
  const blob = new Blob(["QTI ZIP contents"], { type: "application/zip" });
  const response = new Response();
  const readBlob = vi.spyOn(response, "blob").mockResolvedValue(blob);
  vi.mocked(apiFetch).mockResolvedValue(response);
  let download: HTMLAnchorElement | undefined;
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    download = this;
    expect(document.body.contains(this)).toBe(true);
    expect(this.href).toBe("blob:qti-export");
    expect(this.download).toBe("questions-qti-3.0.zip");
  });

  await exportQtiPackage([42, 7]);

  expect(apiFetch).toHaveBeenCalledExactlyOnceWith(
    "/api/question-notebook/practice/export/qti",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_ids: [42, 7], version: "3.0", format: "zip" }),
      cache: "no-store",
    },
  );
  expect(readBlob).toHaveBeenCalledOnce();
  expect(createObjectURL).toHaveBeenCalledExactlyOnceWith(blob);
  expect(click).toHaveBeenCalledOnce();
  expect(download).toBeDefined();
  expect(download!.isConnected).toBe(false);
  expect(revokeObjectURL).not.toHaveBeenCalled();
  vi.advanceTimersByTime(999);
  expect(revokeObjectURL).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:qti-export");
});

it("throws PracticeRequestError for 503 without creating a download", async () => {
  const response = new Response("QTI dependency unavailable", { status: 503 });
  const readBlob = vi.spyOn(response, "blob");
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.mocked(apiFetch).mockResolvedValue(response);

  const result = exportQtiPackage([42]);
  await expect(result).rejects.toBeInstanceOf(PracticeRequestError);
  await expect(result).rejects.toMatchObject({ status: 503, message: "QTI export failed" });
  expect(readBlob).not.toHaveBeenCalled();
  expect(createObjectURL).not.toHaveBeenCalled();
  expect(click).not.toHaveBeenCalled();
  vi.runAllTimers();
  expect(revokeObjectURL).not.toHaveBeenCalled();
});

import { expect, test } from "@playwright/test";
import JSZip from "jszip";

async function illustratedEpub(): Promise<Buffer> {
  const zip = new JSZip();
  zip.file("mimetype", "application/epub+zip", { compression: "STORE" });
  zip.file(
    "META-INF/container.xml",
    "<?xml version='1.0'?><container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OPS/book.opf' media-type='application/oebps-package+xml'/></rootfiles></container>",
  );
  zip.file(
    "OPS/book.opf",
    "<?xml version='1.0'?><package xmlns='http://www.idpf.org/2007/opf' xmlns:dc='http://purl.org/dc/elements/1.1/' version='3.0' unique-identifier='book-id'><metadata><dc:identifier id='book-id'>urn:uuid:deeptutor-reader-test</dc:identifier><dc:title>Faithful reader</dc:title><dc:language>en</dc:language></metadata><manifest><item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/><item id='one' href='one.xhtml' media-type='application/xhtml+xml'/><item id='two' href='two.xhtml' media-type='application/xhtml+xml'/><item id='dot' href='dot.png' media-type='image/png'/></manifest><spine><itemref idref='one'/><itemref idref='two'/></spine></package>",
  );
  zip.file(
    "OPS/nav.xhtml",
    "<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'><body><nav epub:type='toc'><ol><li><a href='one.xhtml'>Illustrated chapter</a></li><li><a href='two.xhtml'>Second chapter</a></li></ol></nav></body></html>",
  );
  zip.file(
    "OPS/one.xhtml",
    "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>Illustrated chapter</title></head><body><h1>Illustrated chapter</h1><p>This layout comes from the EPUB.</p><img alt='source illustration' src='dot.png'/></body></html>",
  );
  zip.file(
    "OPS/two.xhtml",
    "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>Second chapter</title></head><body><h1>Second chapter</h1><p>Keyboard navigation reached the second spine item.</p></body></html>",
  );
  zip.file(
    "OPS/dot.png",
    Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  );
  return zip.generateAsync({ type: "nodebuffer", mimeType: "application/epub+zip" });
}

test("faithfully renders EPUB resources, navigates, and restores its CFI", async ({
  page,
}, testInfo) => {
  const filename = `faithful-reader-${Date.now()}.epub`;
  await page.goto("/home?capability=immersive_reading");
  const fileInput = page
    .getByRole("button", { name: /Open a document to read/i })
    .locator('input[type="file"]');
  await expect(fileInput).toBeAttached();
  await fileInput.setInputFiles({
    name: filename,
    mimeType: "application/epub+zip",
    buffer: await illustratedEpub(),
  });
  const readerFrame = page.locator("iframe").contentFrame();
  await expect(
    readerFrame.getByRole("heading", { name: "Illustrated chapter" }),
  ).toBeVisible();
  await expect(readerFrame.getByAltText("source illustration")).toBeVisible();

  const turnForward =
    testInfo.project.name === "epub-reader-webkit"
      ? () => page.getByRole("button", { name: "Next", exact: true }).click()
      : async () => {
          await readerFrame.getByText("This layout comes from the EPUB.").click();
          await page.keyboard.press("ArrowRight");
        };
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await turnForward();
    if (
      await readerFrame.getByRole("heading", { name: "Second chapter" }).isVisible()
    )
      break;
    await page.waitForTimeout(150);
  }
  await expect(readerFrame.getByRole("heading", { name: "Second chapter" })).toBeVisible();
  await expect
    .poll(async () => {
      const response = await page.request.get("/api/v1/reading/materials");
      const rows = (await response.json()) as Array<{
        material_id: string;
        filename: string;
      }>;
      const material = rows.find((row) => row.filename === filename);
      if (!material) return 0;
      const position = await page.request.get(
        `/api/v1/reading/materials/${material.material_id}/position`,
      );
      return ((await position.json()) as { locator: number }).locator;
    })
    .toBe(2);

  await page.reload();
  await page.getByRole("button", { name: new RegExp(filename, "i") }).click();
  const restoredFrame = page.locator("iframe").contentFrame();
  await expect(restoredFrame.getByRole("heading", { name: "Second chapter" })).toBeVisible();
});

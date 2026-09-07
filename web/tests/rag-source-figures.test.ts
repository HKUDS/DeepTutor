import assert from "node:assert/strict";
import test from "node:test";

import { collectRagSourceFigures } from "../lib/rag-source-figures";

test("collectRagSourceFigures reads image_url and nested images from sources events", () => {
  const figures = collectRagSourceFigures([
    {
      type: "sources",
      metadata: {
        sources: [
          {
            title: "paper.pdf",
            content_type: "image",
            image_url: "/api/knowledge-bases/kb/index-assets/paper.pdf/page-1.png",
            mime_type: "image/png",
            image_description: "NAND gate",
          },
          {
            title: "paper.pdf",
            content_type: "text",
            images: [
              {
                image_url: "/api/knowledge-bases/kb/index-assets/paper.pdf/page-1.png",
              },
              {
                image_url: "/api/knowledge-bases/kb/index-assets/paper.pdf/page-2.png",
                mime_type: "image/png",
              },
            ],
          },
        ],
      },
    },
  ]);

  assert.equal(figures.length, 2);
  assert.equal(
    figures[0].image_url,
    "/api/knowledge-bases/kb/index-assets/paper.pdf/page-1.png",
  );
  assert.equal(figures[0].image_description, "NAND gate");
  assert.equal(
    figures[1].image_url,
    "/api/knowledge-bases/kb/index-assets/paper.pdf/page-2.png",
  );
});

test("collectRagSourceFigures ignores filesystem paths", () => {
  const figures = collectRagSourceFigures([
    {
      type: "sources",
      metadata: {
        sources: [
          {
            image_url: "/tmp/parse_cache/figure.png",
            title: "leaked",
          },
          {
            image_path: "/Users/me/kb/version-1/assets/x.png",
            title: "also leaked",
          },
        ],
      },
    },
  ]);
  assert.deepEqual(figures, []);
});

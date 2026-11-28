# MinerU 4 protocol fixture

This is a synthetic one-page document, validated by DocVortex 0.6.8's published
`MiddleJson.from_dict` and rendered with its real Markdown and structured-content
renderers. It contains text, an equation, a table, and a one-pixel image. It is
not a model-backed MinerU parse or evidence of OCR quality.

`provenance.json` records the source wheel and SHA-256. To regenerate, download
that exact wheel from PyPI and run:

```bash
python tests/fixtures/mineru4-contract/generate.py /path/to/docvortex-0.6.8-cp311-abi3-macosx_14_0_arm64.whl
```

Only pure Python schema/render modules are loaded from the wheel; the native
macOS analyzer is never imported or executed. The subprocess contract test
expands these blocks over a synthetic 13-page PDF and writes the ZIP layout
produced by MinerU 4.1.3's `ParseResult.save`. The test CLI checks the stateless
whole-document arguments and exercises publication, failure, and retry paths.

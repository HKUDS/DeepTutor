# DeepTutor logo assets

The six `color-*` / `black-*` PNGs are the approved source artwork: `logo` is
the standalone symbol, `word` is the wordmark, and `full` is the combined banner.
The root README and translated READMEs use `color-full.png`.

After changing these sources, run:

```sh
npm --prefix web run sync:logo
```

This crops excess transparent padding without changing the artwork, creates
web-sized copies in `web/public/brand`, and regenerates square 16/32 px favicons
and the 180 px Apple touch icon. The application uses `/brand/*` URLs. Legacy
`/logo.png`, `/logo_black.png`, `/banner.png`, and `/logo-ver2.png` URLs also serve
the new artwork so existing saved documents keep working. Commit the generated
public files with any source changes; packaged builds use these public files.

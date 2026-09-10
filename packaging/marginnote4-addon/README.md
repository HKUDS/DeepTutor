# MarginNote 4 add-on for the DeepTutor MN4 bridge

This directory holds the MarginNote 4 add-on that fills a connected
MarginNote 4 knowledge base. It is an MN4-native extension built on the
official extension contract (`JSB.newAddon` factory), with no bundler and
no external dependencies.

Maintained upstream at https://github.com/Constallan/deeptutor-mn4-sync.

## Build

```bash
./build.sh
```

produces `deeptutor-mn4-sync-1.1.2.mnaddon` from `main.js`, `mnaddon.json`
and `logo_44x44.png`. Build outputs are not committed; attach the package
to a release for distribution.

## Install

1. Open `deeptutor-mn4-sync-1.1.2.mnaddon` in MarginNote 4 (or drag it in).
2. The add-on is unsigned — enable "allow unauthenticated add-ons" in
   MarginNote 4 settings.
3. In DeepTutor, create or connect a MarginNote 4 knowledge base, open its
   **Devices** tab and pair a device; paste the one-time credential into
   the add-on's configure dialog together with the server URL and the
   knowledge-base name.

## Compatibility

Tested with MarginNote 4.4.6 (macOS) against a self-hosted DeepTutor
v1.5.16+ (20,434 objects synced). Other MarginNote versions and platforms
are untested.

## License

MIT — see `ATTRIBUTION.md` for the copyright line and third-party credits.

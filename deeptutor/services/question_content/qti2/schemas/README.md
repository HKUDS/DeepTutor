# Pinned offline QTI 2 schemas

These 54 XSD files are the complete recursive `xs:import`/`xs:include`
dependency closure for the four roots below. `inventory.json` records each
original schema URL, local file, byte length and SHA-256. The runtime resolver
accepts only those inventoried URLs and verifies bytes before compiling; no
uploaded `schemaLocation` or network fallback is used.

| Dialect | Item XSD | Package XSD |
| --- | --- | --- |
| 2.1 | `imsqti_v2p1p2.xsd` | `qtiv2p1_imscpv1p2_v1p0.xsd` |
| 2.2 | `imsqti_v2p2p4.xsd` | `qtiv2p2_imscpv1p2_v1p0.xsd` |

The 2.1 item root came from
[1EdTech QTI 2.1](https://www.imsglobal.org/xsd/qti/qtiv2p1/imsqti_v2p1p2.xsd);
the 2.2 item root came from
[1EdTech QTI 2.2](https://purl.imsglobal.org/spec/qti/v2p2/schema/xsd/imsqti_v2p2p4.xsd).
Both package roots came from the corresponding `www.imsglobal.org/xsd/qti/`
profile directories. Dependencies include the declared 1EdTech APIP/metadata,
W3C XML, XInclude, MathML and SSML schemas. The catalog preserves each source
URL rather than treating a same-named file from another release as equivalent.

1EdTech's [specification license](https://www.imsglobal.org/speclicense.html)
governs its QTI 2.2 specification materials; its older
[license page](https://www.imsglobal.org/license.html) is referenced by the 2.1
binding. W3C dependencies are governed by the
[W3C Document License](https://www.w3.org/copyright/document-license/).
The schemas are pinned for local validation and do not imply QTI certification.

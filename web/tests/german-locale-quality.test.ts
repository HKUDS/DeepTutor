import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

function findGermanCatalog(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, "locales", "de", "app.json");
    if (fs.existsSync(candidate)) return candidate;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate locales/de/app.json");
}

const catalog = JSON.parse(
  fs.readFileSync(findGermanCatalog(), "utf8"),
) as Record<string, string>;

test("German activity labels describe actions in progress", () => {
  assert.equal(catalog["Reading skill"], "Skill wird gelesen");
  assert.equal(catalog["Reading source"], "Quelle wird gelesen");
  assert.equal(catalog["Writing file"], "Datei wird geschrieben");
  assert.equal(catalog["Listing files"], "Dateien werden aufgelistet");
  assert.equal(catalog["Writing note"], "Notiz wird geschrieben");
  assert.equal(catalog["Saving memory"], "Memory wird gespeichert");
  assert.equal(catalog["Brainstorming"], "Ideen werden gesammelt");
});

test("German catalog rejects known context-free machine translations", () => {
  const text = Object.values(catalog).join("\n");
  // Each of these is what a translator without context produces for a term of
  // art: RAG as a cloth, LLM as a law degree, a git branch as a bank branch.
  // Matched on word boundaries: German compounds legitimately contain these
  // letter sequences ("ausklappen" ends in "klappen", not in "Lappen").
  const forbidden = [
    "Lappen",
    "Wertmarke",
    "Filiale",
    "Kodex",
    "Master of Laws",
    "Klapprechner",
    "Endstelle",
    "Einbettung",
    "Aufforderungstext",
  ];
  for (const term of forbidden) {
    assert.equal(
      new RegExp(`\\b${term}\\b`, "iu").test(text),
      false,
      `Found rejected machine translation: ${term}`,
    );
  }
});

test("German UI keeps one term per concept", () => {
  const text = Object.values(catalog).join("\n");
  // The catalog was translated in several passes; these are the variants that
  // crept in and were normalised away. Keep them out.
  const offSpec = [
    "Wissensdatenbank",
    "Wissensbasis",
    "Konversation",
    "Lernendenprofil",
    "Erziehungsberechtigte",
    "Meisterungspfad",
  ];
  for (const fragment of offSpec) {
    assert.equal(
      text.includes(fragment),
      false,
      `Found off-glossary term: ${fragment}`,
    );
  }
});

test("German UI uses the informal second person consistently", () => {
  const text = Object.values(catalog).join("\n");
  // Imperative forms are unambiguous: the polite "Sie" imperative cannot be
  // confused with "sie" meaning they. Bare "Sie" is not checked for that reason.
  for (const formal of [
    "Klicken Sie",
    "Wählen Sie",
    "Geben Sie",
    "Öffnen Sie",
    "Versuchen Sie",
    "Stellen Sie sicher",
    "Bitte warten Sie",
    "Beachten Sie",
    "Prüfen Sie",
    "Laden Sie",
  ]) {
    assert.equal(
      text.includes(formal),
      false,
      `Found formal-address copy: ${formal}`,
    );
  }
});

test("German UI avoids the em dash", () => {
  // One string describes the literal "—" the usage table renders for a
  // missing measurement; that dash is the thing being named, not prose.
  const text = Object.entries(catalog)
    .filter(([key]) => !key.includes("Missing measurements appear as —"))
    .map(([, value]) => value)
    .join("\n");
  assert.equal(text.includes("—"), false, "Found em dash in German catalog");
});

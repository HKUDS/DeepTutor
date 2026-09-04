import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

function findSpanishCatalog(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, "locales", "es", "app.json");
    if (fs.existsSync(candidate)) return candidate;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate locales/es/app.json");
}

const catalog = JSON.parse(
  fs.readFileSync(findSpanishCatalog(), "utf8"),
) as Record<string, string>;

test("Spanish activity labels describe actions in progress", () => {
  assert.equal(catalog["Reading skill"], "Consultando una habilidad");
  assert.equal(catalog["Reading source"], "Consultando una fuente");
  assert.equal(catalog["Writing file"], "Escribiendo un archivo");
  assert.equal(catalog["Listing files"], "Listando archivos");
  assert.equal(catalog["Writing note"], "Escribiendo una nota");
  assert.equal(catalog["Saving memory"], "Guardando en memoria");
  assert.equal(catalog["Brainstorming"], "Lluvia de ideas");
});

test("Spanish catalog rejects known context-free machine translations", () => {
  const text = Object.values(catalog).join("\n");
  const forbidden = [
    "TRAPO",
    "Máster en Derecho",
    "Maestría en Derecho",
    "computadora portátil",
    "fogonadura",
    "rebaja",
    "Códice",
    "punto final",
    "incrustación",
    "próxima sucursal",
  ];
  for (const fragment of forbidden) {
    assert.equal(
      text.toLocaleLowerCase("es").includes(fragment.toLocaleLowerCase("es")),
      false,
      `Found rejected machine translation: ${fragment}`,
    );
  }
});

test("Spanish UI uses the informal second person consistently", () => {
  const text = Object.values(catalog).join("\n");
  for (const formal of [
    "usted",
    "haga clic",
    "seleccione",
    "ingrese",
    "compruebe",
    "espere",
    "libere",
    "empiece",
    "inténtelo",
    "siga",
  ]) {
    assert.equal(
      new RegExp(`\\b${formal}\\b`, "iu").test(text),
      false,
      `Found formal-address copy: ${formal}`,
    );
  }
});

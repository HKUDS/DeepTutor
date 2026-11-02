import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

import type { ModuleStatus } from "../../../hooks/useModules";

// Model the source checkout's installed modules from the authoritative catalog.
// Browser-only audits have no backend to answer this deployment inventory API.
const manifests = resolve(__dirname, "../../../../deeptutor/modules/manifests");
export const sourceModuleInventory: { modules: ModuleStatus[] } = {
  modules: readdirSync(manifests).filter(name => name.endsWith(".json")).map(name => {
    const manifest = JSON.parse(readFileSync(resolve(manifests, name), "utf8"));
    return {
      id: manifest.id,
      installed: true,
      enabled: true,
      ready: true,
      navigation: manifest.navigation,
      issues: [],
    };
  }),
};

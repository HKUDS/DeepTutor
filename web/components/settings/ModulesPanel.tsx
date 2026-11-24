"use client";

import { useTranslation } from "react-i18next";
import { useModules } from "@/hooks/useModules";

// Same card language as SettingSection: a quiet bordered surface with a
// 13.5px header. It used to be its own `rounded-xl border p-5` island with an
// 18px heading, which read as a different product next to the other cards.
export default function ModulesPanel() {
  const { t } = useTranslation();
  const { modules, error, reload } = useModules();
  return (
    <section className="mb-4 rounded-xl border border-[color-mix(in_srgb,var(--border)_60%,transparent)] bg-[color-mix(in_srgb,var(--muted)_10%,var(--background))] px-4 md:px-5">
      <header className="pb-1 pt-3.5">
        <h2 className="text-[13.5px] font-semibold tracking-tight text-[var(--foreground)]">
          {t("Modules")}
        </h2>
        <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t("Stop DeepTutor before changing modules. Removing a module keeps your data.")}
        </p>
      </header>
      {error && <button onClick={reload}>{t("Retry")}</button>}
      {!modules && !error && <p aria-busy="true">{t("Loading...")}</p>}
      <div className="overflow-x-auto pb-2">
        <table className="w-full text-left text-[13px]">
          <thead>
            <tr className="text-[12.5px] text-[var(--muted-foreground)]">
              <th className="w-[34%] py-2 pr-3 text-left font-medium">{t("Module")}</th>
              <th className="whitespace-nowrap px-2 py-2 text-left font-medium">{t("Installed")}</th>
              <th className="whitespace-nowrap px-2 py-2 text-left font-medium">{t("Enabled")}</th>
              <th className="whitespace-nowrap px-2 py-2 text-left font-medium">{t("Ready")}</th>
              <th className="min-w-[220px] py-2 pl-2 text-left font-medium">{t("Command")}</th>
            </tr>
          </thead>
          <tbody>{modules?.map(module => <tr key={module.id} className="border-t border-[color-mix(in_srgb,var(--border)_50%,transparent)] align-top">
            <td className="py-2.5 pr-3"><code>{module.id}</code>
              {module.issues.map(issue => <p key={issue} className="mt-1 max-w-md text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">{issue}</p>)}
            </td>
            {[module.installed, module.enabled, module.ready].map((value, index) =>
              <td className="px-2 py-2.5" key={index}>{value ? t("Yes") : t("No")}</td>)}
            <td className="py-2.5 pl-2"><code className="break-words">{module.id === "core" ? "—" :
              `deeptutor module ${!module.installed ? "install" : !module.enabled ? "enable" : "disable"} ${module.id}`}</code></td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}

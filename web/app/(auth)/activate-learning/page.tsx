"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { activateLearningAccount } from "@/lib/auth";

export default function ActivateLearningPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const result = await activateLearningAccount(username, code, password);
    setBusy(false);
    if (result.ok) router.push("/login");
    else setError(result.error || t("Activation failed"));
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-[var(--background)] p-5">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
        <div>
          <h1 className="text-lg font-semibold text-[var(--foreground)]">{t("Activate learning account")}</h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">{t("Use the one-time code from your administrator, then choose your password.")}</p>
        </div>
        <label className="block text-sm text-[var(--foreground)]">
          {t("Username")}
          <input value={username} onChange={(event) => setUsername(event.target.value)} required className="mt-1 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3" />
        </label>
        <label className="block text-sm text-[var(--foreground)]">
          {t("Activation code")}
          <input value={code} onChange={(event) => setCode(event.target.value)} required autoComplete="one-time-code" className="mt-1 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 font-mono" />
        </label>
        <label className="block text-sm text-[var(--foreground)]">
          {t("New password")}
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} autoComplete="new-password" className="mt-1 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3" />
        </label>
        {error ? <p role="alert" className="text-sm text-[var(--destructive)]">{error}</p> : null}
        <button type="submit" disabled={busy} className="h-10 w-full rounded-lg bg-[var(--primary)] font-medium text-[var(--primary-foreground)] disabled:opacity-50">{busy ? t("Activating…") : t("Activate")}</button>
        <Link href="/login" className="block text-center text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]">{t("Back to sign in")}</Link>
      </form>
    </main>
  );
}

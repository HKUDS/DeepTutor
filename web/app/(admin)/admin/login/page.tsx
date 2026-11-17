"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ShieldCheck } from "lucide-react";
import { PRODUCT_NAME_FA } from "@/lib/brand";
import { login, fetchAuthStatus } from "@/lib/auth";

/**
 * A separate entrance for the admin panel.
 *
 * `DECISIONS.md` D-004 and `MASTER_SPEC.md` put the admin entry at
 * `/admin/login`, and the Phase 0 audit recorded it as MISSING. It stays
 * separate on purpose: the operator who manages users is not the same person
 * browsing the learning app, and pointing both at one form means the admin
 * screen inherits the user app's framing.
 *
 * It authenticates exactly like `/login` — same `login()`, same
 * `mustChangePassword` handling — and adds one rule on top: a valid account
 * that is not an administrator is refused here rather than allowed through to
 * bounce off the middleware a moment later. The two failures read differently,
 * because "you are not an administrator" is not a forgotten password.
 */
function AdminLoginContent() {
  const { t } = useTranslation();
  const router = useRouter();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);

  // Already signed in as an administrator? Go straight in. A signed-in
  // non-admin is left on the form so they can sign in as themselves instead of
  // being told, confusingly, that they are already logged in.
  useEffect(() => {
    let alive = true;
    fetchAuthStatus().then((status) => {
      if (!alive) return;
      if (status?.authenticated && status.role === "admin") {
        router.replace("/admin/users");
        return;
      }
      setChecking(false);
    });
    return () => {
      alive = false;
    };
  }, [router]);

  const handleSubmit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setError("");
      setLoading(true);

      const result = await login(username, password);
      if (!result.ok) {
        setError(result.error ?? t("Login failed"));
        setLoading(false);
        return;
      }

      if (result.mustChangePassword) {
        router.replace("/profile?change=1");
        return;
      }

      // `login()` returns only success and the password-change flag, so the
      // role is read from the status endpoint it just invalidated. Widening
      // login()'s return type would touch every caller for one screen's need.
      const status = await fetchAuthStatus();
      if (status?.role !== "admin") {
        // Deliberately not a redirect: the person needs to read why. The
        // session stands — they are signed in, just not here for this.
        setError(t("This account does not have administrator access."));
        setLoading(false);
        return;
      }

      router.replace("/admin/users");
    },
    [username, password, router, t],
  );

  if (checking) {
    return (
      <div className="w-full max-w-sm text-center text-sm text-[var(--muted-foreground)]">
        {t("Loading sign in...")}
      </div>
    );
  }

  return (
    <div className="w-full max-w-sm mx-auto">
      <div className="mb-8">
        <div className="flex items-center gap-2.5 mb-5">
          <ShieldCheck
            size={20}
            strokeWidth={1.7}
            className="text-[var(--primary)]"
          />
          <span className="text-xs font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
            {t("Administration")}
          </span>
        </div>
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
          {t("Sign in to the admin panel")}
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {PRODUCT_NAME_FA}
        </p>
      </div>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-sm px-8 py-8">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label
              htmlFor="admin-username"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Email or username")}
            </label>
            <input
              id="admin-username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                         bg-[var(--background)] text-[var(--foreground)]
                         placeholder:text-[var(--muted-foreground)]
                         focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                         transition-shadow text-sm"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label
              htmlFor="admin-password"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Password")}
            </label>
            <input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                         bg-[var(--background)] text-[var(--foreground)]
                         placeholder:text-[var(--muted-foreground)]
                         focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                         transition-shadow text-sm"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="text-sm text-red-500 bg-red-500/10 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 rounded-lg font-medium text-sm
                       bg-[var(--primary)] text-[var(--primary-foreground)]
                       hover:opacity-90 active:opacity-80
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-opacity"
          >
            {loading ? t("Signing in…") : t("Sign in")}
          </button>
        </form>
      </div>

      <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">
        <Link href="/login" className="text-[var(--primary)] hover:underline font-medium">
          {t("Back to the learning app")}
        </Link>
      </p>
    </div>
  );
}

export default function AdminLoginPage() {
  const { t } = useTranslation();
  return (
    <Suspense
      fallback={
        <div className="w-full max-w-sm text-center text-sm text-[var(--muted-foreground)]">
          {t("Loading sign in...")}
        </div>
      }
    >
      <AdminLoginContent />
    </Suspense>
  );
}

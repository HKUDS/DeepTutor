"use client";

import { Suspense, useCallback, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { productName } from "@/lib/brand";
import { AuthBrandPanel } from "@/components/auth/AuthBrandPanel";
import { LoginPhone } from "@/components/auth/LoginPhone";
import { login, fetchAuthStatus, checkIsFirstUser } from "@/lib/auth";
import {
  inheritLoginHash,
  normalizeInternalReturnPath,
} from "@/shared/auth/return-url";

function LoginPageContent() {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = normalizeInternalReturnPath(searchParams.get("next"));
  const resolvedNext = useCallback(
    () =>
      inheritLoginHash(
        next,
        typeof window === "undefined" ? "" : window.location.hash,
      ),
    [next],
  );

  const registered = searchParams.get("registered") === "1";

  // Which credential the card is asking for.
  //
  // Password is the default even though D-005 makes phone the sign-up path.
  // Reasons, in order of weight:
  //   * every existing account (and the bootstrap administrator) has a
  //     password and may not have a phone number yet;
  //   * the Gate 1 browser suite signs in through this form, and changing the
  //     default would replace a green acceptance gate with a regression;
  //   * a user who has never signed up reaches the phone tab, which is one
  //     visible, labelled click away.
  // Reversing this is a product decision, not a refactor.
  const [mode, setMode] = useState<"phone" | "password">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // If already authenticated, skip login
    fetchAuthStatus().then((status) => {
      if (status?.authenticated) {
        router.replace(resolvedNext());
        return;
      }
      // No users registered yet — send straight to the registration page
      checkIsFirstUser().then((first) => {
        if (first) router.replace("/register");
      });
    });
  }, [router, resolvedNext]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    const result = await login(username, password);

    if (result.ok) {
      // A password an admin assigned is temporary by definition — send the
      // owner straight to the form rather than letting them settle in with it.
      router.replace(
        result.mustChangePassword ? "/profile?change=1" : resolvedNext(),
      );
    } else {
      setError(result.error ?? t("Login failed"));
      setLoading(false);
    }
  }

  return (
    <>
      <AuthBrandPanel />

      <div className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="w-full max-w-sm mx-auto">
          {/* Below `lg` the panel is hidden, so the wordmark returns here: a
              phone user still needs to know which product they opened. */}
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <img
              src="/brand/color-logo.png"
              alt=""
              aria-hidden="true"
              width={32}
              height={32}
              className="h-8 w-8 rounded-lg"
            />
            <span className="font-serif text-lg font-semibold text-[var(--foreground)]">
              {productName(i18n.language)}
            </span>
          </div>

          <div className="mb-8">
            <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
              {t("Sign in to your account")}
            </h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t("Welcome back")}
            </p>
          </div>

      {/* Registered success notice */}
      {registered && (
        <div className="mb-4 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-600 dark:text-green-400">
          {t("Account created! Sign in to continue.")}
        </div>
      )}

      {/* Card */}
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-sm px-8 py-8">
        <div
          role="tablist"
          aria-label={t("Sign-in method")}
          className="grid grid-cols-2 gap-1 p-1 mb-6 rounded-lg bg-[var(--muted)]"
        >
          {(["phone", "password"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              onClick={() => setMode(value)}
              className={
                "py-1.5 rounded-md text-sm font-medium transition-colors " +
                (mode === value
                  ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]")
              }
            >
              {value === "phone" ? t("Phone") : t("Password")}
            </button>
          ))}
        </div>

        {mode === "phone" ? (
          <LoginPhone />
        ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Email or username */}
          <div>
            <label
              htmlFor="username"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Email or username")}
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                         bg-[var(--background)] text-[var(--foreground)]
                         placeholder:text-[var(--muted-foreground)]
                         focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                         transition-shadow text-sm"
              placeholder="you@example.com"
            />
          </div>

          {/* Password */}
          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Password")}
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                         bg-[var(--background)] text-[var(--foreground)]
                         placeholder:text-[var(--muted-foreground)]
                         focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                         transition-shadow text-sm"
              placeholder="••••••••"
            />
          </div>

          {/* Error message */}
          {error && (
            <p className="text-sm text-red-500 bg-red-500/10 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {/* Submit */}
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
        )}
      </div>

      <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">
        {t("Don't have an account?")}{" "}
        <Link
          href="/register"
          className="text-[var(--primary)] hover:underline font-medium"
        >
          {t("Create one")}
        </Link>
      </p>

          <p className="mt-10 text-center text-xs text-[var(--muted-foreground)]">
            {t("DeepTutor · Agent-Native Learning")}
          </p>
        </div>
      </div>
    </>
  );
}

export default function LoginPage() {
  const { t } = useTranslation();
  return (
    <Suspense
      fallback={
        <div className="w-full max-w-sm text-center text-sm text-[var(--muted-foreground)]">
          {t("Loading sign in...")}
        </div>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}

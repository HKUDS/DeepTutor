"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  fetchAuthStatus,
  register,
  requestRegistrationCode,
} from "@/lib/auth";

export default function RegisterPage() {
  const { t } = useTranslation();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchAuthStatus().then((status) => {
      if (status?.authenticated) router.replace("/");
    });
  }, [router]);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = window.setInterval(() => {
      setCountdown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [countdown]);

  async function handleRequestCode(e: React.SyntheticEvent) {
    e.preventDefault();
    setError("");
    setNotice("");

    if (password !== confirmPassword) {
      setError(t("Passwords do not match"));
      return;
    }
    if (countdown > 0) return;

    setLoading(true);
    const result = await requestRegistrationCode(email, password);
    if (result.ok) {
      setCodeSent(true);
      setCountdown(60);
      setNotice(t("If this email can register, a verification code has been sent."));
    } else {
      setError(result.error ?? t("Could not send verification code"));
    }
    setLoading(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setNotice("");

    if (!codeSent) {
      setError(t("Request a verification code first"));
      return;
    }

    setLoading(true);
    const result = await register(email, code);

    if (result.ok) {
      // The backend sets the session cookie after the code is consumed.
      router.replace("/");
    } else {
      setError(result.error ?? t("Registration failed"));
      setLoading(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      <div className="text-center mb-8">
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
          DeepTutor
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t("Create your account")}
        </p>
      </div>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-sm px-8 py-8">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Email")}
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
              htmlFor="password"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Password")}
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
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
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("At least 8 characters")}
            </p>
          </div>

          <div>
            <label
              htmlFor="confirmPassword"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Confirm password")}
            </label>
            <input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                         bg-[var(--background)] text-[var(--foreground)]
                         placeholder:text-[var(--muted-foreground)]
                         focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                         transition-shadow text-sm"
              placeholder="••••••••"
            />
          </div>

          <button
            type="button"
            onClick={handleRequestCode}
            disabled={loading || countdown > 0}
            className="w-full py-2.5 px-4 rounded-lg border border-[var(--border)] font-medium text-sm
                       text-[var(--foreground)] hover:bg-[var(--background)]
                       disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading
              ? t("Sending verification code…")
              : countdown > 0
                ? t("Resend in {{seconds}}s", { seconds: countdown })
                : codeSent
                  ? t("Resend verification code")
                  : t("Send verification code")}
          </button>

          {codeSent && (
            <div>
              <label
                htmlFor="code"
                className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
              >
                {t("Email verification code")}
              </label>
              <input
                id="code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                           bg-[var(--background)] text-[var(--foreground)] tracking-[0.35em]
                           focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                           transition-shadow text-sm"
              />
            </div>
          )}

          {error && (
            <p className="text-sm text-red-500 bg-red-500/10 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {notice && (
            <p className="text-sm text-green-600 dark:text-green-400 bg-green-500/10 rounded-lg px-3 py-2">
              {notice}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !codeSent}
            className="w-full py-2.5 px-4 rounded-lg font-medium text-sm
                       bg-[var(--primary)] text-[var(--primary-foreground)]
                       hover:opacity-90 active:opacity-80
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-opacity"
          >
            {loading ? t("Creating account…") : t("Verify and create account")}
          </button>
        </form>
      </div>

      <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">
        {t("Already have an account?")} {" "}
        <Link
          href="/login"
          className="text-[var(--primary)] hover:underline font-medium"
        >
          {t("Sign in")}
        </Link>
      </p>

      <p className="mt-3 text-center text-xs text-[var(--muted-foreground)]">
        DeepTutor · Agent-Native Learning
      </p>
    </div>
  );
}

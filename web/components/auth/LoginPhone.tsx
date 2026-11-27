"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Loader2 } from "lucide-react";
import { apiFetch, apiUrl } from "@/lib/api";

/**
 * Phone sign-up and sign-in by one-time code (Phase 2, D-005).
 *
 * Two steps in one card rather than two routes: the code is only meaningful in
 * the context of the number that requested it, and a separate URL invites a
 * user to bookmark a screen that cannot work on its own.
 *
 * The resend timer is server-driven (`resend_in`), not a guessed 60 in the
 * component. When the server says wait, waiting is what the button does.
 */

type Step = "phone" | "code";

interface RequestResponse {
  ok: boolean;
  expires_in: number;
  resend_in: number;
}

export function LoginPhone() {
  const { t } = useTranslation();

  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const codeRef = useRef<HTMLInputElement>(null);

  // Count the resend cooldown down to zero. `setInterval` is cleared on every
  // dependency change so a second request cannot leave two timers running.
  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = setInterval(() => setSecondsLeft((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(timer);
  }, [secondsLeft > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const requestCode = useCallback(async () => {
    setError("");
    setBusy(true);
    try {
      const res = await apiFetch(apiUrl("/api/auth/otp/request"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
        skipAuthRedirect: true,
      });

      const data = (await res.json().catch(() => ({}))) as Partial<RequestResponse> & {
        detail?: string;
      };

      if (!res.ok) {
        // A 429 carries retry-after in seconds; using it keeps the button
        // honest about when it will work again.
        const retry = Number(res.headers.get("Retry-After"));
        if (res.status === 429 && Number.isFinite(retry) && retry > 0) {
          setSecondsLeft(Math.ceil(retry));
        }
        setError(data.detail ?? t("We could not send the code. Please try again."));
        return;
      }

      setStep("code");
      setSecondsLeft(data.resend_in ?? 60);
      // Focus moves to the code field, so a user who was on a phone keyboard
      // does not have to tap again.
      requestAnimationFrame(() => codeRef.current?.focus());
    } catch {
      setError(t("Could not reach the server."));
    } finally {
      setBusy(false);
    }
  }, [phone, t]);

  const verifyCode = useCallback(async () => {
    setError("");
    setBusy(true);
    try {
      const res = await apiFetch(apiUrl("/api/auth/otp/verify"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, code, purpose: "signup" }),
        skipAuthRedirect: true,
      });

      const data = (await res.json().catch(() => ({}))) as {
        detail?: string;
        is_admin?: boolean;
      };

      if (!res.ok) {
        setError(data.detail ?? t("The code is incorrect or has expired."));
        setCode("");
        return;
      }

      // A full navigation rather than a client route change: the session cookie
      // is set by this response, and the server needs to see it on the next
      // document request for the admin gate and the shell to agree.
      window.location.assign(data.is_admin ? "/admin" : "/");
    } catch {
      setError(t("Could not reach the server."));
    } finally {
      setBusy(false);
    }
  }, [phone, code, t]);

  const inputClass =
    "w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)] " +
    "bg-[var(--background)] text-[var(--foreground)] " +
    "placeholder:text-[var(--muted-foreground)] " +
    "focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent " +
    "transition-shadow text-sm";

  return (
    <div className="space-y-5">
      {step === "phone" ? (
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            void requestCode();
          }}
        >
          <div>
            <label
              htmlFor="phone"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Phone number")}
            </label>
            <input
              id="phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              dir="ltr"
              required
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              className={inputClass}
              placeholder="0912 345 6789"
            />
            <p className="mt-1.5 text-xs text-[var(--muted-foreground)]">
              {t("We will send a code to this number.")}
            </p>
          </div>

          {error && <ErrorLine message={error} />}

          <button
            type="submit"
            disabled={busy || !phone.trim()}
            className="w-full py-2.5 px-4 rounded-lg font-medium text-sm
                       bg-[var(--primary)] text-[var(--primary-foreground)]
                       hover:opacity-90 active:opacity-80
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-opacity inline-flex items-center justify-center gap-2"
          >
            {busy && <Loader2 size={16} className="animate-spin" />}
            {busy ? t("Sending…") : t("Send code")}
          </button>
        </form>
      ) : (
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            void verifyCode();
          }}
        >
          <div>
            <label
              htmlFor="otp-code"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Verification code")}
            </label>
            <input
              id="otp-code"
              ref={codeRef}
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              dir="ltr"
              required
              maxLength={8}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              className={inputClass + " tracking-[0.4em] text-center text-lg"}
              placeholder="······"
            />
            <p className="mt-1.5 text-xs text-[var(--muted-foreground)]" dir="ltr">
              {phone}
            </p>
          </div>

          {error && <ErrorLine message={error} />}

          <button
            type="submit"
            disabled={busy || code.length < 4}
            className="w-full py-2.5 px-4 rounded-lg font-medium text-sm
                       bg-[var(--primary)] text-[var(--primary-foreground)]
                       hover:opacity-90 active:opacity-80
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-opacity inline-flex items-center justify-center gap-2"
          >
            {busy && <Loader2 size={16} className="animate-spin" />}
            {busy ? t("Signing in…") : t("Sign in")}
          </button>

          <div className="flex items-center justify-between text-sm">
            <button
              type="button"
              onClick={() => {
                setStep("phone");
                setCode("");
                setError("");
              }}
              className="inline-flex items-center gap-1.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            >
              <ArrowLeft size={14} />
              {t("Change number")}
            </button>

            <button
              type="button"
              disabled={busy || secondsLeft > 0}
              onClick={() => void requestCode()}
              className="text-[var(--primary)] hover:underline font-medium disabled:opacity-50 disabled:no-underline disabled:cursor-not-allowed"
            >
              {secondsLeft > 0
                ? t("Resend in {{seconds}}s", { seconds: secondsLeft })
                : t("Resend code")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function ErrorLine({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="text-sm text-red-500 bg-red-500/10 rounded-lg px-3 py-2"
    >
      {message}
    </p>
  );
}

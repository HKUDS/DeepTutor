import { useTranslation } from "react-i18next";


/**
 * The identity panel beside the auth form.
 *
 * It exists for one reason: before anyone signs in, this is the only place the
 * product can say what it *is*. A bare centred card said only "sign in", which
 * is indistinguishable from any other app's login — a poor first impression for
 * a product whose whole premise is helping someone learn.
 *
 * Rendered in the reading direction of the page (`dir` is set on `<html>` by the
 * i18n provider), so it mirrors without a physical property anywhere.
 */
export function AuthBrandPanel() {
  const { t } = useTranslation();

  return (
    <aside className="hidden lg:flex flex-col justify-between gap-10 p-12 bg-[var(--muted)] border-e border-[var(--border)]">
      <div className="flex items-center gap-3">
        {/* The mark is decorative here: the heading below names the product,
            so a screen reader would otherwise say it twice. */}
        <img
          src="/brand/color-logo.png"
          alt=""
          aria-hidden="true"
          width={36}
          height={36}
          className="h-9 w-9 rounded-lg"
        />
        <span className="font-serif text-lg font-semibold text-[var(--foreground)]">
          {t("Darsyar")}
        </span>
      </div>

      <div className="max-w-md">
        <h2 className="font-serif text-3xl font-semibold leading-snug text-[var(--foreground)]">
          {t("A learning companion that works the way you do")}
        </h2>
        <p className="mt-4 text-sm leading-relaxed text-[var(--muted-foreground)]">
          {t("Agent-native learning companion")}
        </p>
      </div>

      <ul className="space-y-3 text-sm text-[var(--muted-foreground)]">
        {[
          t("Study from your own sources"),
          t("Practice and track what you have learned"),
          t("Always know which source an answer came from"),
        ].map((line) => (
          <li key={line} className="flex items-start gap-2.5">
            <span
              aria-hidden="true"
              className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--primary)]"
            />
            <span>{line}</span>
          </li>
        ))}
      </ul>
    </aside>
  );
}

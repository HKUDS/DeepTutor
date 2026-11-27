import { Bot } from "lucide-react";
import { providerIconSpec } from "@/lib/provider-branding";

/** Locally bundled provider marks; no third-party request is needed to render them. */
export default function ProviderIcon({
  provider,
  size = 13,
  className = "",
}: {
  provider?: string | null;
  size?: number;
  className?: string;
}) {
  const spec = providerIconSpec(provider);
  if (!spec) {
    return <Bot size={size} strokeWidth={1.7} aria-hidden className={`shrink-0 ${className}`.trim()} />;
  }
  return (
    <span
      aria-hidden
      className={`inline-flex shrink-0 items-center justify-center ${className}`.trim()}
      style={{ width: size, height: size }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/provider-icons/${spec.file}`}
        alt=""
        width={size}
        height={size}
        draggable={false}
        className={`h-full w-full select-none object-contain ${spec.darkFile ? "dark:hidden" : spec.mono ? "dark:invert" : ""}`}
      />
      {spec.darkFile && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`/provider-icons/${spec.darkFile}`}
          alt=""
          width={size}
          height={size}
          draggable={false}
          className="hidden h-full w-full select-none object-contain dark:block"
        />
      )}
    </span>
  );
}

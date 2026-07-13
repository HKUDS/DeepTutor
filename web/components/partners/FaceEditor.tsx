"use client";

/**
 * iOS-contacts-style face editor: a large live preview on top, then an emoji
 * grid, a background color row, and photo/SVG upload. Emoji + color compose
 * (the color is the disc behind the emoji); an uploaded image wins over both
 * and any emoji tap switches back to emoji mode.
 */

import { useRef, useState } from "react";
import { ImagePlus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import PartnerAvatar, {
  PARTNER_COLORS,
} from "@/components/partners/PartnerAvatar";

export const FACE_EMOJIS = [
  "🦊",
  "🐳",
  "🦉",
  "🐱",
  "🐶",
  "🐼",
  "🐨",
  "🦁",
  "🐯",
  "🐸",
  "🐙",
  "🦄",
  "🤖",
  "👾",
  "🌱",
  "🌸",
  "🍀",
  "🌙",
  "✨",
  "🔥",
  "📚",
  "🎨",
  "🎧",
  "🧭",
] as const;

export interface FaceValue {
  emoji: string;
  color: string;
  avatar: string; // data URL; "" = none
}

const AVATAR_SIZE = 128;
const SVG_MAX_BYTES = 100 * 1024;
const RASTER_MAX_BYTES = 10 * 1024 * 1024;

async function fileToAvatarDataUrl(file: File): Promise<string> {
  if (file.type === "image/svg+xml") {
    if (file.size > SVG_MAX_BYTES) {
      throw new Error("svg-too-large");
    }
    const text = await file.text();
    const base64 = btoa(String.fromCharCode(...new TextEncoder().encode(text)));
    return `data:image/svg+xml;base64,${base64}`;
  }
  if (!/^image\/(png|jpe?g|webp|gif)$/.test(file.type)) {
    throw new Error("unsupported-type");
  }
  if (file.size > RASTER_MAX_BYTES) {
    throw new Error("file-too-large");
  }
  // Center-crop to a square and downscale — avatars render at ≤56px, so
  // 128px keeps config payloads tiny without visible quality loss.
  const bitmap = await createImageBitmap(file);
  try {
    const side = Math.min(bitmap.width, bitmap.height);
    const sx = (bitmap.width - side) / 2;
    const sy = (bitmap.height - side) / 2;
    const canvas = document.createElement("canvas");
    canvas.width = AVATAR_SIZE;
    canvas.height = AVATAR_SIZE;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas-unavailable");
    ctx.drawImage(bitmap, sx, sy, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
    const webp = canvas.toDataURL("image/webp", 0.9);
    return webp.startsWith("data:image/webp")
      ? webp
      : canvas.toDataURL("image/png");
  } finally {
    bitmap.close();
  }
}

export default function FaceEditor({
  name,
  value,
  onChange,
}: {
  name: string;
  value: FaceValue;
  onChange: (next: FaceValue) => void;
}) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadError, setUploadError] = useState("");

  const hasImage = Boolean(value.avatar);

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setUploadError("");
    try {
      const avatar = await fileToAvatarDataUrl(file);
      onChange({ ...value, avatar });
    } catch (e) {
      const code = e instanceof Error ? e.message : "";
      setUploadError(
        code === "unsupported-type"
          ? t("Use a PNG, JPG, WebP, GIF, or SVG image.")
          : code === "svg-too-large" || code === "file-too-large"
            ? t("That file is too large.")
            : t("Could not read that image."),
      );
    }
  };

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Live preview */}
      <PartnerAvatar
        name={name || "?"}
        emoji={value.emoji}
        color={value.color}
        image={value.avatar}
        size={88}
        className="shadow-sm"
      />

      {/* Emoji grid — tapping any emoji leaves image mode */}
      <div className="grid grid-cols-8 gap-1.5">
        {FACE_EMOJIS.map((preset) => {
          const active = !hasImage && value.emoji === preset;
          return (
            <button
              key={preset}
              type="button"
              onClick={() =>
                onChange({
                  ...value,
                  avatar: "",
                  emoji: active ? "" : preset,
                })
              }
              className={`flex h-9 w-9 items-center justify-center rounded-full border text-[17px] transition-colors ${
                active
                  ? "border-[var(--primary)] bg-[var(--secondary)]"
                  : "border-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]"
              }`}
            >
              {preset}
            </button>
          );
        })}
      </div>

      {/* Background colors — the disc behind the emoji / initial */}
      <div
        className={`flex items-center gap-2 ${hasImage ? "pointer-events-none opacity-35" : ""}`}
        aria-disabled={hasImage}
      >
        {PARTNER_COLORS.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-label={preset}
            onClick={() =>
              onChange({
                ...value,
                color: value.color === preset ? "" : preset,
              })
            }
            className="flex h-6 w-6 items-center justify-center rounded-full transition-transform hover:scale-110"
            style={{ background: preset }}
          >
            {value.color === preset && (
              <span className="h-2 w-2 rounded-full bg-white/90" />
            )}
          </button>
        ))}
      </div>

      {/* Upload / remove */}
      <div className="flex items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
          className="hidden"
          onChange={(e) => {
            void handleFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] font-medium text-[var(--foreground)] hover:border-[var(--ring)]"
        >
          <ImagePlus className="h-3.5 w-3.5" />
          {hasImage ? t("Replace photo") : t("Upload photo or SVG")}
        </button>
        {hasImage && (
          <button
            type="button"
            onClick={() => onChange({ ...value, avatar: "" })}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <X className="h-3.5 w-3.5" />
            {t("Remove")}
          </button>
        )}
      </div>
      {uploadError && (
        <p className="text-[12px] text-[var(--destructive)]">{uploadError}</p>
      )}
    </div>
  );
}

"use client";

/**
 * A collection's folder tint. The server keeps only the key; the tone is a
 * `--folder-*` token in globals.css so a palette change never needs a
 * migration and dark themes get their own shade. "" is the neutral folder
 * every collection had before colours existed.
 */
export const FOLDER_COLORS = [
  { key: "", label: "Default", tone: "var(--folder-default)" },
  { key: "blue", label: "Blue", tone: "var(--folder-blue)" },
  { key: "teal", label: "Teal", tone: "var(--folder-teal)" },
  { key: "green", label: "Green", tone: "var(--folder-green)" },
  { key: "amber", label: "Amber", tone: "var(--folder-amber)" },
  { key: "orange", label: "Orange", tone: "var(--folder-orange)" },
  { key: "rose", label: "Rose", tone: "var(--folder-rose)" },
  { key: "violet", label: "Violet", tone: "var(--folder-violet)" },
  { key: "slate", label: "Slate", tone: "var(--folder-slate)" },
] as const;

export function folderTone(color: string | undefined): string {
  return (
    FOLDER_COLORS.find((row) => row.key === (color ?? ""))?.tone ??
    FOLDER_COLORS[0].tone
  );
}

/**
 * A folder drawn with one sheet peeking out per file (up to three), so an
 * empty collection reads as empty at a glance.
 */
export function FolderGlyph({
  color,
  files,
  size = 56,
  className,
}: {
  color?: string;
  files: number;
  size?: number;
  className?: string;
}) {
  const tone = folderTone(color);
  const sheets = Math.min(Math.max(files, 0), 3);
  return (
    <svg
      viewBox="0 0 64 50"
      width={size}
      height={(size * 50) / 64}
      aria-hidden
      className={className}
    >
      <path
        d="M4 8a4 4 0 0 1 4-4h13.6a4 4 0 0 1 2.9 1.2L28 9h28a4 4 0 0 1 4 4v29a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4Z"
        fill={`color-mix(in srgb, ${tone} 82%, black)`}
      />
      {Array.from({ length: sheets }, (_, index) => (
        <rect
          key={index}
          x={10 + index * 3}
          y={12 - index * 2.5}
          width={44 - index * 6}
          height={28}
          rx={2}
          fill="var(--card)"
          stroke={`color-mix(in srgb, ${tone} 35%, var(--border))`}
          strokeWidth={0.8}
        />
      ))}
      <path
        d="M4 20a4 4 0 0 1 4-4h48a4 4 0 0 1 4 4v22a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4Z"
        fill={tone}
      />
      <path
        d="M8 16.5h48"
        stroke="white"
        strokeOpacity={0.28}
        strokeWidth={1}
      />
    </svg>
  );
}

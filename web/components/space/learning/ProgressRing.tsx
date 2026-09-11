/**
 * A topic's completion, drawn as a ring.
 *
 * This replaced a system emoji sitting in a bordered tile. The emoji was
 * whatever the model happened to pick, rendered at whatever the OS font
 * decided — it carried no information and read as clip art. The ring is the
 * one number the card is actually about, and it inherits the theme.
 *
 * Three things it deliberately is not:
 *
 * A *bare integer* in a circle. "7" with no unit is an id, a step number, an
 * avatar badge — anything but a measurement. The figure carries a small `%`
 * so it reads as the quantity it is, and the two are set at different sizes
 * so the number stays the thing you see.
 *
 * *Action-coloured*. `--primary` is what buttons and links are, and the card
 * this sits on is itself one big link. An arc in that blue competes with the
 * title for the eye and quietly suggests it can be clicked. So the arc is
 * ink — the page's own foreground — and `--primary` is kept for the single
 * moment it means something: the path is finished.
 *
 * *Heavy*. The stroke is a hairline, and the unfilled track is dimmer than
 * the border it is drawn from. A ring is a footnote to the title next to it;
 * at 2.5px it read as the loudest thing on the card, and at low percentages
 * a thick round cap turns a real value into what looks like a stuck spinner.
 */
export function ProgressRing({
  value,
  size = 32,
  stroke = 1.75,
  showLabel = true,
}: {
  /** Completion in 0..1. */
  value: number;
  size?: number;
  stroke?: number;
  showLabel?: boolean;
}) {
  const safe = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const percent = Math.round(safe * 100);
  const complete = safe >= 1;

  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} aria-hidden="true" className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={stroke}
          opacity={0.45}
        />
        {safe > 0 && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={complete ? "var(--primary)" : "var(--foreground)"}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - safe)}
            opacity={complete ? 1 : 0.7}
            className="transition-[stroke-dashoffset] duration-500"
          />
        )}
      </svg>
      {showLabel && (
        <span className="absolute flex items-baseline text-[var(--muted-foreground)]">
          <span className="text-[11px] font-medium leading-none tabular-nums">
            {percent}
          </span>
          <span className="text-[7px] font-medium leading-none opacity-70">
            %
          </span>
        </span>
      )}
    </span>
  );
}

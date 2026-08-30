import "@/components/space/learning/mastery-theme.css";

/**
 * Page shell for Mastery Path.
 *
 * This surface used to live at `/space/learning`, inside `SpaceMain` — which
 * meant every screen wore a "back to the Learning Space" bar above its own
 * header, two back affordances stacked on top of each other pointing at
 * different places. A learning path is not a section of the Space hub the way
 * a persona list is: it is a destination you stay in, so it owns its route and
 * its own full-height shell. Each screen supplies whatever back link it needs
 * — the study screen returns to its topic, the topic to the atlas, the atlas
 * to nothing.
 */
export default function MasteryLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--background)]">
      {children}
    </div>
  );
}

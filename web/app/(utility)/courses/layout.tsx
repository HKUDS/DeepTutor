/**
 * Page shell for the Courses surface.
 *
 * Courses used to live under `/space`, where `SpaceMain` supplied both the
 * document container and a "back to the hub" link. A course is not a section of
 * the Learning Space — it is the container the other surfaces hang off — so it
 * owns its own route and therefore its own shell. The back link is left to the
 * detail page, which knows it has a parent; the index has none.
 */
export default function CoursesLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-5xl px-8 py-8 pb-12">{children}</div>
    </div>
  );
}

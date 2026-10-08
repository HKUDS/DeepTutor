import { FeaturePage } from "@/components/layout/FeaturePage";

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
    <FeaturePage>{children}</FeaturePage>
  );
}

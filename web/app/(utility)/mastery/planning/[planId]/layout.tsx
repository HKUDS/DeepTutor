import { ReadingProvider } from "@/context/ReadingContext";
import { WatchingProvider } from "@/context/WatchingContext";

/** Planning conversations render shared rich assistant content, so they need
 * the same media contexts as ordinary chat without joining the study-session
 * ChatRuntimeProvider. */
export default function LearningPlanLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <ReadingProvider>
      <WatchingProvider>{children}</WatchingProvider>
    </ReadingProvider>
  );
}

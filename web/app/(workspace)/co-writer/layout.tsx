import { GeogebraTabProvider } from "@/context/GeogebraTabContext";
import { QuizFollowupProvider } from "@/context/QuizFollowupContext";

/**
 * Dito, the note page's companion, is a conversation in the workspace-level
 * chat runtime, so it needs the same viewer providers the reading companion
 * gets from its layout (quiz follow-ups, the GeoGebra tab).
 */
export default function NotesLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <QuizFollowupProvider>
      <GeogebraTabProvider>{children}</GeogebraTabProvider>
    </QuizFollowupProvider>
  );
}

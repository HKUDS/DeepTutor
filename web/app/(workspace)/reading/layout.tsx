import { GeogebraTabProvider } from "@/context/GeogebraTabContext";
import { QuizFollowupProvider } from "@/context/QuizFollowupContext";

/**
 * Reading uses the workspace-level runtime. Route/session selection isolates
 * its transcript without opening a second WebSocket or store.
 */
export default function ReadingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <QuizFollowupProvider>
      <GeogebraTabProvider>{children}</GeogebraTabProvider>
    </QuizFollowupProvider>
  );
}

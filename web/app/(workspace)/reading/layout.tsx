import { GeogebraTabProvider } from "@/context/GeogebraTabContext";
import { QuizFollowupProvider } from "@/context/QuizFollowupContext";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";

/**
 * Reading owns its conversation runtime. The workspace shell above also hosts
 * Home's provider so Home can keep a turn alive while navigation occurs, but a
 * reader must never render that provider's transcript or live stream.
 */
export default function ReadingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <UnifiedChatProvider>
      <QuizFollowupProvider>
        <GeogebraTabProvider>{children}</GeogebraTabProvider>
      </QuizFollowupProvider>
    </UnifiedChatProvider>
  );
}

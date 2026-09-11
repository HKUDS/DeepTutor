import { GeogebraTabProvider } from "@/context/GeogebraTabContext";
import { QuizFollowupProvider } from "@/context/QuizFollowupContext";
import { ChatRuntimeProvider } from "@/features/chat";
import { ReadingProvider } from "@/context/ReadingContext";
import { WatchingProvider } from "@/context/WatchingContext";

/**
 * The chat engine is scoped to the study session, not to the whole Mastery
 * workspace. The atlas and the topic detail page never talk to it, and it owns
 * a WebSocket plus the streaming reducer — mounting it around them made every
 * map view pay for a connection it does not use.
 */
export default function MasteryStudyLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <ReadingProvider>
      <WatchingProvider>
        <ChatRuntimeProvider>
          <QuizFollowupProvider>
            <GeogebraTabProvider>{children}</GeogebraTabProvider>
          </QuizFollowupProvider>
        </ChatRuntimeProvider>
      </WatchingProvider>
    </ReadingProvider>
  );
}

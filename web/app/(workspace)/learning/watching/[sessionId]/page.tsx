import LegacyWatchingSession from "@/components/reading/workspace/LegacyWatchingSession";
export default async function WatchingPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <LegacyWatchingSession sessionId={sessionId} />;
}

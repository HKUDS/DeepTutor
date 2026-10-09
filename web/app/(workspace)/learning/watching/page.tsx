import { redirect } from "next/navigation";
import { READING_HOME } from "@/lib/learning-routes";
import WatchingTranscriptRedirect from "@/components/reading/WatchingTranscriptRedirect";

export default async function WatchingPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const incoming = await searchParams;
  const sourceUrl = typeof incoming.video === "string" ? incoming.video : "";
  if (!/^https:\/\//i.test(sourceUrl)) redirect(READING_HOME);
  const title = typeof incoming.title === "string" ? incoming.title : "Video";
  return <WatchingTranscriptRedirect sourceUrl={sourceUrl} title={title} />;
}

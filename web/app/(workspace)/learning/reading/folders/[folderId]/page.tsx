import { ReadingFolderPage } from "@/components/reading/library/ReadingFolder";

export default async function ImmersiveReadingFolderRoute({
  params,
}: {
  params: Promise<{ folderId: string }>;
}) {
  const { folderId } = await params;
  return <ReadingFolderPage folderId={decodeURIComponent(folderId)} />;
}

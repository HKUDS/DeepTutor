import { redirect } from "next/navigation";
import { READING_HOME } from "@/lib/learning-routes";
export default async function WatchingPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const incoming = await searchParams;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(incoming)) if (typeof value === "string") query.set(key, value);
  redirect(READING_HOME + (query.size ? `?${query}` : ""));
}

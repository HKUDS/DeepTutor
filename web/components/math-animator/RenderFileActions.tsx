"use client";
import { OutputFileActions } from "@/components/files/OutputFileActions";

export function RenderFileActions({ url }: { url: string }) {
  return <OutputFileActions key={url} url={url} kind="render" />;
}

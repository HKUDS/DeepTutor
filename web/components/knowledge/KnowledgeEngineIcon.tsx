import { Database } from "lucide-react";

/**
 * Brand marks for knowledge engines and live knowledge sources.
 *
 * Assets are vendored under /public so the Knowledge Center keeps working in
 * offline/self-hosted deployments. LightRAG deliberately uses the HKUDS
 * organization avatar for both its embedded and server variants.
 */
const KNOWLEDGE_ICONS: Record<string, string> = {
  llamaindex: "/knowledge-engine-icons/llamaindex.png",
  pageindex: "/knowledge-engine-icons/pageindex.png",
  "pageindex-oss": "/knowledge-engine-icons/pageindex.png",
  graphrag: "/knowledge-engine-icons/graphrag.png",
  lightrag: "/knowledge-engine-icons/lightrag.jpg",
  "lightrag-server": "/knowledge-engine-icons/lightrag.jpg",
  ima: "/knowledge-engine-icons/tencent-ima.svg",
  obsidian: "/knowledge-engine-icons/obsidian.svg",
  marginnote4: "/knowledge-engine-icons/marginnote.png",
};

export function knowledgeSourceIconId(input: {
  provider?: string | null;
  type?: string | null;
}): string {
  if (input.type === "obsidian") return "obsidian";
  if (input.type === "marginnote4") return "marginnote4";
  return input.provider || "llamaindex";
}

export default function KnowledgeEngineIcon({
  engine,
  size = 20,
  className = "",
}: {
  engine?: string | null;
  size?: number;
  className?: string;
}) {
  const source = engine ? KNOWLEDGE_ICONS[engine] : undefined;
  if (!source) {
    return (
      <Database
        size={size}
        strokeWidth={1.7}
        className={`shrink-0 ${className}`.trim()}
      />
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={source}
      alt=""
      aria-hidden
      width={size}
      height={size}
      draggable={false}
      className={`shrink-0 select-none object-contain ${className}`.trim()}
    />
  );
}

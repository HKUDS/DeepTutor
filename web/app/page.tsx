"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Root page redirects to Notebooks (NotebookLM-style entry point)
 */
export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/notebooks");
  }, [router]);

  return (
    <div className="h-screen flex items-center justify-center bg-slate-50">
      <div className="animate-pulse text-slate-400">正在加载...</div>
    </div>
  );
}

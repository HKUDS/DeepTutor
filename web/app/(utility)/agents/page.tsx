import AgentsHub from "@/components/agents/AgentsHub";

export default function AgentsPage() {
  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-6xl px-6 py-10 pb-16 md:px-10">
        <AgentsHub />
      </div>
    </div>
  );
}

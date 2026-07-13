import MemoryHub from "@/components/memory/MemoryHub";

export default function MemoryPage() {
  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-6xl px-6 py-10 pb-16 md:px-10">
        <MemoryHub />
      </div>
    </div>
  );
}

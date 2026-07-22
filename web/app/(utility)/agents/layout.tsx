// Bare shell — the page owns its own padding + scroll (a scrollable hub with a
// max-width container), matching the other top-level consoles (memory).
export default function AgentsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <main className="flex h-full min-h-0 flex-col bg-[var(--background)]">
      {children}
    </main>
  );
}

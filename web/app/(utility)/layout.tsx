import UtilitySidebar from "@/components/sidebar/UtilitySidebar";

export default function UtilityLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="flex h-[100dvh] overflow-hidden">
      <UtilitySidebar />
      <main className="min-w-0 flex-1 overflow-hidden bg-[var(--background)] pb-[calc(72px+env(safe-area-inset-bottom))] md:pb-0">
        {children}
      </main>
    </div>
  );
}

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-[var(--background)]">
      {children}
    </div>
  );
}

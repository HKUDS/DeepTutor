export default function LearningLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="flex h-full min-h-0 flex-col bg-[var(--background)]">{children}</div>
}

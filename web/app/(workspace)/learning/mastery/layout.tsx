import '@/components/space/learning/mastery-theme.css'

/** Theme scope only; learning inherits its runtime from the workspace. */
export default function MasteryLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="flex h-full min-h-0 flex-col bg-[var(--background)]">{children}</div>
}

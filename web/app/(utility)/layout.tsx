import UtilitySidebar from '@/components/sidebar/UtilitySidebar'

export default function UtilityLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return <UtilitySidebar>{children}</UtilitySidebar>
}

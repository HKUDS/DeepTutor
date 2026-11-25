import SpaceMain from "@/components/space/SpaceMain";

export default function SpaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return <SpaceMain>{children}</SpaceMain>;
}

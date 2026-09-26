import SettingsPageContent from "@/components/settings/SettingsPageContent";

export default async function SettingsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  return <SettingsPageContent section={section} />;
}

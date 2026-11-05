import { SettingsPage } from "@/components/next/settings/settings-page";

export default async function Page({ params }: { params: Promise<{ scope: string; section: string }> }) {
  const { scope, section } = await params;
  return <SettingsPage scope={scope} slug={section} />;
}

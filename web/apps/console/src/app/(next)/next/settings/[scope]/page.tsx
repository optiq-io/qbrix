import { notFound, redirect } from "next/navigation";
import { isSettingsScope, settingsHref, settingsSections } from "@/components/next/settings/section";

export default async function Page({ params }: { params: Promise<{ scope: string }> }) {
  const { scope } = await params;
  if (!isSettingsScope(scope)) notFound();
  redirect(settingsHref(scope, settingsSections[scope][0].slug));
}

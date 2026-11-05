"use client";

import { notFound } from "next/navigation";
import { findSection, isSettingsScope } from "./section";
import { SettingsTitle } from "./settings-frame";
import { ThemeSwitch } from "./theme-switch";
import { YourConnections } from "./your-connections";

export function SettingsPage({ scope, slug }: { scope: string; slug: string }) {
  const section = isSettingsScope(scope) ? findSection(scope, slug) : undefined;
  if (!section) notFound();

  if (scope === "you" && slug === "connections") return <YourConnections />;
  if (scope === "you" && slug === "appearance") {
    return (
      <>
        <SettingsTitle title="Appearance">Light, dark, or follow the system. Only this browser keeps it.</SettingsTitle>
        <div>
          <ThemeSwitch />
        </div>
      </>
    );
  }
  return <SettingsTitle title={section.label} />;
}

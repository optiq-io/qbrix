import { routes } from "@/config/routes";

export type SettingsScope = "you" | "workspace";

export type SettingsSection = { slug: string; label: string };

export const settingsSections: Record<SettingsScope, SettingsSection[]> = {
  you: [
    { slug: "profile", label: "Profile" },
    { slug: "appearance", label: "Appearance" },
    { slug: "connections", label: "Your connections" },
  ],
  workspace: [
    { slug: "general", label: "General" },
    { slug: "members", label: "Members" },
    { slug: "keys", label: "Keys" },
    { slug: "alerts", label: "Alerts" },
    { slug: "github", label: "GitHub" },
  ],
};

export function isSettingsScope(value: string): value is SettingsScope {
  return value === "you" || value === "workspace";
}

export function findSection(scope: SettingsScope, slug: string): SettingsSection | undefined {
  return settingsSections[scope].find((section) => section.slug === slug);
}

export function settingsHref(scope: SettingsScope, slug: string): string {
  return scope === "you" ? routes.next.yourSettings(slug) : routes.next.workspaceSettings(slug);
}

export const yourSettingsHome = settingsHref("you", settingsSections.you[0].slug);
export const workspaceSettingsHome = settingsHref("workspace", settingsSections.workspace[0].slug);

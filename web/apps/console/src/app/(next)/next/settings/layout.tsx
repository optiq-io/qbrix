import { SettingsFrame } from "@/components/next/settings/settings-frame";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <SettingsFrame>{children}</SettingsFrame>;
}

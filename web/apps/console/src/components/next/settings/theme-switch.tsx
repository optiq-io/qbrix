"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { Segmented } from "@qbrix/ui/next/segmented";
import { useTheme, type Theme } from "@qbrix/ui/lib/theme";

const OPTIONS: { value: Theme; label: string; icon: React.ReactNode }[] = [
  { value: "light", label: "Light", icon: <Sun size={13} /> },
  { value: "dark", label: "Dark", icon: <Moon size={13} /> },
  { value: "system", label: "Follow the system", icon: <Monitor size={13} /> },
];

export function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  return <Segmented label="Theme" value={theme} options={OPTIONS} onChange={setTheme} boxed />;
}

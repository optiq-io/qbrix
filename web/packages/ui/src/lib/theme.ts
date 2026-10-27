"use client";

import { useCallback, useSyncExternalStore } from "react";
import { STORAGE_KEY } from "./theme-script";

export type Theme = "system" | "light" | "dark";

const listeners = new Set<() => void>();

function read(): Theme {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return;
    apply(read());
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function apply(theme: Theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

export function useTheme(): { theme: Theme; setTheme: (theme: Theme) => void } {
  const theme = useSyncExternalStore(subscribe, read, () => "system" as const);

  const setTheme = useCallback((next: Theme) => {
    try {
      if (next === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, next);
    } catch {}
    apply(next);
    listeners.forEach((listener) => listener());
  }, []);

  return { theme, setTheme };
}

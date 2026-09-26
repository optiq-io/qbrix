"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { usePathname } from "next/navigation";

const STORAGE_KEY = "qbrix:sidebar:expanded";

type SidebarState = {
  // desktop: the 292px panel replaces (xl) or overlays (lg) the 64px rail
  expanded: boolean;
  toggle: () => void;
  collapse: () => void;
  // below lg the rail is a top bar and the panel opens as a sheet
  sheetOpen: boolean;
  openSheet: () => void;
  closeSheet: () => void;
};

const SidebarContext = createContext<SidebarState | null>(null);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  // always false on the server and on the first client render — reading
  // localStorage during render would mismatch the streamed html.
  const [expanded, setExpanded] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setExpanded(window.localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  const toggle = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev;
      window.localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  const collapse = useCallback(() => {
    setExpanded(false);
    window.localStorage.setItem(STORAGE_KEY, "false");
  }, []);

  const openSheet = useCallback(() => setSheetOpen(true), []);
  const closeSheet = useCallback(() => setSheetOpen(false), []);

  // navigating is the sheet's most common exit
  useEffect(() => {
    setSheetOpen(false);
  }, [pathname]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "\\") {
        e.preventDefault();
        toggle();
      }
      if (e.key === "Escape") setSheetOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [toggle]);

  return (
    <SidebarContext.Provider
      value={{ expanded, toggle, collapse, sheetOpen, openSheet, closeSheet }}
    >
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar(): SidebarState {
  const ctx = useContext(SidebarContext);
  if (!ctx) throw new Error("useSidebar must be used inside SidebarProvider");
  return ctx;
}

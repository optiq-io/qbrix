"use client";

import { useEffect } from "react";

const PALETTE = "qbrix:next:palette";
const SHORTCUTS = "qbrix:next:shortcuts";

export function openPalette() {
  window.dispatchEvent(new Event(PALETTE));
}

export function openShortcuts() {
  window.dispatchEvent(new Event(SHORTCUTS));
}

export function useOpenRequest(kind: "palette" | "shortcuts", onOpen: () => void) {
  useEffect(() => {
    const name = kind === "palette" ? PALETTE : SHORTCUTS;
    window.addEventListener(name, onOpen);
    return () => window.removeEventListener(name, onOpen);
  }, [kind, onOpen]);
}

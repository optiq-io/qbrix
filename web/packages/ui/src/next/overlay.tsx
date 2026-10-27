"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export const SCRIM = "bg-[#19191866]";

export const PANEL = "rounded-n-panel border border-n-line bg-n-surface";

export function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
}

/** escape, a tab trap, the scroll lock, and focus in on open and back on close */
export function useOverlay(
  open: boolean,
  onClose: () => void,
  panelRef: React.RefObject<HTMLElement | null>,
) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const panel = panelRef.current;
    (panel && focusables(panel)[0] ? focusables(panel)[0] : panel)?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const items = focusables(panelRef.current);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panelRef.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, [open, panelRef]);
}

/** portals into the nearest next scope, so the overlay takes that scope's theme
    rather than whatever the system or <body> says */
export function OverlayPortal({ children }: { children: React.ReactNode }) {
  const sentinelRef = useRef<HTMLSpanElement>(null);
  const [target, setTarget] = useState<Element | null>(null);

  useLayoutEffect(() => {
    const sentinel = sentinelRef.current;
    if (sentinel) setTarget(sentinel.closest('[data-console="next"]') ?? document.body);
  }, []);

  return (
    <>
      <span ref={sentinelRef} hidden />
      {target && createPortal(children, target)}
    </>
  );
}

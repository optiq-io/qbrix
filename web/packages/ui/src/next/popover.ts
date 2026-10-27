"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** the open state and keyboard model a menu and a picker share: arrows, Home and End
    move between items, Escape closes and returns focus to the trigger, Tab and an
    outside click close */
export function usePopover(itemRole: "menuitem" | "option") {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const items = useCallback(
    () =>
      Array.from(
        contentRef.current?.querySelectorAll<HTMLElement>(`[role="${itemRole}"]`) ?? [],
      ),
    [itemRole],
  );

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const list = items();
    (list.find((el) => el.getAttribute("aria-selected") === "true") ?? list[0])?.focus();

    const onDown = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, items]);

  const onContentKeyDown = (e: React.KeyboardEvent) => {
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLElement);
    const move = (to: number) => {
      e.preventDefault();
      list[(to + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(list.length - 1);
    else if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "Tab") setOpen(false);
  };

  const onTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
    }
  };

  return {
    open,
    setOpen,
    close,
    wrapperRef,
    triggerRef,
    contentRef,
    onContentKeyDown,
    onTriggerKeyDown,
  };
}

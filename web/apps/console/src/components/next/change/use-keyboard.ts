"use client";

import { useEffect, useRef } from "react";

const TYPING = "input, textarea, select, [contenteditable='true']";

export function changeRowId(key: string) {
  return `change-row-${key}`;
}

export function focusRow(key: string) {
  const row = document.getElementById(changeRowId(key));
  row?.querySelector<HTMLElement>("button[aria-pressed]")?.focus({ preventScroll: true });
  row?.scrollIntoView({ block: "nearest" });
}

export function useChangeKeys({
  keys,
  selected,
  onSelect,
  onUndo,
}: {
  keys: string[];
  selected: string | null;
  onSelect: (key: string) => void;
  onUndo: () => void;
}) {
  const latest = useRef({ keys, selected, onSelect, onUndo });
  latest.current = { keys, selected, onSelect, onUndo };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (event.target instanceof Element && event.target.closest(TYPING)) return;
      const { keys, selected, onSelect, onUndo } = latest.current;

      if (event.key === "u") {
        event.preventDefault();
        onUndo();
        return;
      }
      if (event.key !== "j" && event.key !== "k") return;
      event.preventDefault();
      const at = selected ? keys.indexOf(selected) : -1;
      const next = keys[event.key === "j" ? at + 1 : Math.max(at - 1, 0)];
      if (!next) return;
      onSelect(next);
      focusRow(next);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

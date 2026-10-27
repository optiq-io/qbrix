"use client";

import { cloneElement, useEffect, useId, useRef, useState } from "react";
import { cn } from "../lib/utils";
import { PANEL } from "./overlay";

const OPEN_DELAY_MS = 400;
const CLOSE_DELAY_MS = 150;

/** more about a thing on hover or keyboard focus: an "others" band's options, a pull
    request's details. the trigger must itself be focusable (a link or a button) */
export function HoverCard({
  trigger,
  align = "left",
  className,
  children,
}: {
  trigger: React.ReactElement<{ "aria-describedby"?: string }>;
  align?: "left" | "right";
  className?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const id = useId();

  const schedule = (next: boolean, delay: number) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(next), delay);
  };

  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span
      className="relative inline-flex"
      onPointerEnter={() => schedule(true, OPEN_DELAY_MS)}
      onPointerLeave={() => schedule(false, CLOSE_DELAY_MS)}
      onFocus={() => schedule(true, 0)}
      onBlur={() => schedule(false, CLOSE_DELAY_MS)}
    >
      {cloneElement(trigger, { "aria-describedby": open ? id : undefined })}
      {open && (
        <span
          id={id}
          role="tooltip"
          className={cn(
            PANEL,
            "absolute top-[calc(100%+6px)] z-30 flex w-max max-w-[340px] flex-col gap-1.5 p-3 text-left shadow-[0_8px_24px_#0000001f]",
            align === "right" ? "right-0" : "left-0",
            className,
          )}
        >
          {children}
        </span>
      )}
    </span>
  );
}

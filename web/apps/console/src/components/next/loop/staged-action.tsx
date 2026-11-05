"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Consequence } from "@qbrix/ui/next/staged";

export type StagedAction = "launch" | "delete" | "resume";

/** actions that show their consequence first, one open at a time. `state` is what they
    depend on: when it moves, say another person got there first, an open block closes */
export function useStagedAction(state: string) {
  const [staging, setStaging] = useState<StagedAction | null>(null);
  const returnFocus = useRef(false);

  useEffect(() => setStaging(null), [state]);

  // the action hides while its block is open, so it comes back as a new element
  const actionRef = useCallback((action: HTMLButtonElement | null) => {
    if (!action || !returnFocus.current) return;
    returnFocus.current = false;
    action.focus();
  }, []);

  return {
    staging,
    actionRef,
    open: useCallback((action: StagedAction) => setStaging(action), []),
    cancel: useCallback(() => {
      returnFocus.current = true;
      setStaging(null);
    }, []),
    finish: useCallback(() => setStaging(null), []),
  };
}

export function StagedPanel({
  title,
  field,
  action,
  children,
}: {
  title: string;
  field?: React.ReactNode;
  action: React.ReactNode;
  children: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
    panel.current?.scrollIntoView({ block: "nearest" });
  }, []);

  return (
    <div ref={panel} tabIndex={-1} className="rounded-n-panel outline-none">
      <Consequence title={title} field={field} action={action}>
        {children}
      </Consequence>
    </div>
  );
}

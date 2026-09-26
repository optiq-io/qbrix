"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

// every experiment board swaps the page-head action row per tab — Overview
// draws Pause/Edit/Commit, Policy draws Discard/Save changes. the head lives in
// the layout, so a tab needs a way to say "I have unsaved work".
//
// what a tab registers is a *descriptor*, not a ReactNode: the layout owns the
// button styling next to its other pills, and a node rebuilt on every render
// would loop through this state.

export type PendingEdit = {
  onSave: () => void;
  onDiscard: () => void;
  saving: boolean;
  /** the tab has unsaved work but it is not valid to send */
  saveDisabled: boolean;
};

type Ctx = {
  pending: PendingEdit | null;
  setPending: (p: PendingEdit | null) => void;
  tool: React.ReactNode;
  setTool: (n: React.ReactNode) => void;
};

const HeaderActionsContext = createContext<Ctx | null>(null);

export function HeaderActionsProvider({
  children,
}: {
  children: (state: {
    pending: PendingEdit | null;
    tool: React.ReactNode;
  }) => React.ReactNode;
}) {
  const [pending, setPending] = useState<PendingEdit | null>(null);
  const [tool, setTool] = useState<React.ReactNode>(null);
  const value = useMemo(
    () => ({ pending, setPending, tool, setTool }),
    [pending, tool],
  );

  return (
    <HeaderActionsContext.Provider value={value}>
      {children({ pending, tool })}
    </HeaderActionsContext.Provider>
  );
}

/** register (or clear) the head's pending-edit actions for as long as a tab is
    mounted. pass null when the tab has nothing unsaved. */
export function usePendingEdit(pending: PendingEdit | null) {
  const ctx = useContext(HeaderActionsContext);
  const setPending = ctx?.setPending;
  const { onSave, onDiscard, saving, saveDisabled } = pending ?? {};
  const active = pending !== null;

  useEffect(() => {
    if (!setPending) return;
    setPending(
      active && onSave && onDiscard
        ? {
            onSave,
            onDiscard,
            saving: !!saving,
            saveDisabled: !!saveDisabled,
          }
        : null,
    );
    // clears on unmount, so navigating to another tab restores the normal row
    return () => setPending(null);
  }, [setPending, active, onSave, onDiscard, saving, saveDisabled]);
}

/** mount a tab-owned control in the head, left of the standard actions — the
 *  Insights board puts its range selector there. unlike `usePendingEdit` this
 *  does hold a node, so the caller MUST pass a memoized element: an element
 *  rebuilt every render would re-register on every render. */
export function useHeaderTool(node: React.ReactNode) {
  const ctx = useContext(HeaderActionsContext);
  const setTool = ctx?.setTool;

  useEffect(() => {
    if (!setTool) return;
    setTool(node);
    return () => setTool(null);
  }, [setTool, node]);
}

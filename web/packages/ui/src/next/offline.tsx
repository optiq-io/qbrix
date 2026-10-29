"use client";

import { createContext, useContext } from "react";
import { WifiOff } from "lucide-react";

const FrozenContext = createContext<Date | null>(null);

/** while `since` is set the server isn't answering: live figures freeze as of then,
    and edit controls are absent until it answers again */
export function FrozenProvider({ since, children }: { since: Date | null; children: React.ReactNode }) {
  return <FrozenContext.Provider value={since}>{children}</FrozenContext.Provider>;
}

/** when the server stopped answering, or null while it answers */
export function useFrozen(): Date | null {
  return useContext(FrozenContext);
}

export function frozenAt(since: Date): string {
  return since.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** the bar under the top bar while the server isn't answering; it goes away by itself */
export function Offline({ onRetry }: { onRetry: () => void }) {
  const since = useFrozen();
  if (!since) return null;

  return (
    <div role="status" className="n-meta flex items-center gap-2 bg-n-fill-1 px-4 py-2 lg:px-8">
      <WifiOff size={14} className="shrink-0 text-n-text-2" />
      <p className="min-w-0 flex-1">
        <span className="font-medium text-n-text-1">Can&apos;t reach qbrix since {frozenAt(since)}.</span>{" "}
        <span className="text-n-text-2">
          The figures are as they were then, and changes wait until it&apos;s back. Trying again every 10 seconds.
        </span>
      </p>
      <button type="button" onClick={onRetry} className="shrink-0 font-medium text-n-text-1 hover:underline">
        Try now
      </button>
    </div>
  );
}

import { useSyncExternalStore } from "react";

let since: Date | null = null;
const listeners = new Set<() => void>();

function set(next: Date | null) {
  if (next === since || (next && since)) return;
  since = next;
  listeners.forEach((listener) => listener());
}

/** a request never reached the proxy, or the gateway in front of it answered for it */
export function markUnreachable(): void {
  set(new Date());
}

export function markReachable(): void {
  set(null);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** when qbrix stopped answering, or null while it answers */
export function useUnreachableSince(): Date | null {
  return useSyncExternalStore(
    subscribe,
    () => since,
    () => null,
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/types";

// the pre-auth limiter answers 429 with Retry-After in whole seconds. holding
// the deadline rather than the remaining count keeps the countdown honest when
// the tab is backgrounded and the interval stops firing.

export function useRetryAfter() {
  const [remaining, setRemaining] = useState(0);
  const deadline = useRef(0);

  useEffect(() => {
    if (remaining <= 0) return;
    const id = setInterval(() => {
      const left = Math.ceil((deadline.current - Date.now()) / 1000);
      setRemaining(left > 0 ? left : 0);
    }, 500);
    return () => clearInterval(id);
  }, [remaining]);

  // returns true when it consumed the error, so the caller skips its own
  // message and does not also render a bare "too many requests"
  const capture = useCallback((err: unknown): boolean => {
    if (!(err instanceof ApiError) || err.status !== 429) return false;
    // 60 is the limiter's own WINDOW_SEC, so it is the true upper bound rather
    // than an invented number, for the case where the header never arrives
    const seconds = err.retryAfter && err.retryAfter > 0 ? err.retryAfter : 60;
    deadline.current = Date.now() + seconds * 1000;
    setRemaining(seconds);
    return true;
  }, []);

  return { remaining, blocked: remaining > 0, capture };
}

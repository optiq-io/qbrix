"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import Link from "next/link";
import { Pin, PinOff, X } from "lucide-react";
import { AccentDot } from "@qbrix/ui/components/accent-dot";
import { cn } from "@qbrix/ui/lib/utils";
import { routes } from "@/config/routes";

const STORAGE_KEY = "qbrix:pinned-experiments";
// the panel gives the list a fixed band; beyond this it scrolls rather than
// pushing the user chip off the bottom.
const MAX_VISIBLE_HEIGHT = 190;

export type PinnedExperiment = { id: string; name: string };

type PinnedState = {
  pins: PinnedExperiment[];
  isPinned: (id: string) => boolean;
  toggle: (item: PinnedExperiment) => void;
  unpin: (id: string) => void;
};

const PinnedContext = createContext<PinnedState | null>(null);

function read(): PinnedExperiment[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (p): p is PinnedExperiment =>
        !!p && typeof p.id === "string" && typeof p.name === "string",
    );
  } catch {
    // a hand-edited or half-written value shouldn't take the shell down
    return [];
  }
}

// pinning is client-side only — no endpoint stores it, so the list lives in
// localStorage and is deliberately not synced across devices.
export function PinnedProvider({ children }: { children: React.ReactNode }) {
  const [pins, setPins] = useState<PinnedExperiment[]>([]);

  useEffect(() => {
    setPins(read());
  }, []);

  const persist = useCallback((next: PinnedExperiment[]) => {
    setPins(next);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }, []);

  const isPinned = useCallback(
    (id: string) => pins.some((p) => p.id === id),
    [pins],
  );

  const unpin = useCallback(
    (id: string) => persist(pins.filter((p) => p.id !== id)),
    [pins, persist],
  );

  const toggle = useCallback(
    (item: PinnedExperiment) =>
      persist(
        pins.some((p) => p.id === item.id)
          ? pins.filter((p) => p.id !== item.id)
          : [...pins, item],
      ),
    [pins, persist],
  );

  return (
    <PinnedContext.Provider value={{ pins, isPinned, toggle, unpin }}>
      {children}
    </PinnedContext.Provider>
  );
}

export function usePinned(): PinnedState {
  const ctx = useContext(PinnedContext);
  if (!ctx) throw new Error("usePinned must be used inside PinnedProvider");
  return ctx;
}

// board `Console Shell` / Sidebar: a PINNED label over 36px rows, each a dot
// and a name. the board tints two of four dots $accent and two $info against a
// header reading "two have called a winner" — that is a convergence signal the
// API does not expose, so the dot here is inert until it can be told the truth.
export function PinnedSection({ currentId }: { currentId?: string }) {
  const { pins, unpin } = usePinned();
  if (pins.length === 0) return null;

  return (
    <div className="flex min-h-0 flex-col gap-[10px]">
      <span className="px-[11px] font-mono text-[11.5px] uppercase tracking-[0.14em] text-text-faint">
        Pinned
      </span>
      <div
        className="flex flex-col gap-[2px] overflow-y-auto"
        style={{ maxHeight: MAX_VISIBLE_HEIGHT }}
      >
        {pins.map((pin) => {
          const active = pin.id === currentId;
          return (
            <div key={pin.id} className="group/pin relative">
              <Link
                href={routes.experimentDetail(pin.id)}
                className={cn(
                  "flex h-9 items-center gap-3 rounded-[9px] px-[11px] transition-colors",
                  active ? "bg-bg-hover" : "hover:bg-bg-hover",
                )}
              >
                <AccentDot size={7} tone="faint" />
                <span
                  className={cn(
                    "truncate pr-6 text-[14.5px]",
                    active ? "text-text-primary" : "text-text-dim",
                  )}
                >
                  {pin.name}
                </span>
              </Link>
              <button
                type="button"
                onClick={() => unpin(pin.id)}
                aria-label={`Unpin ${pin.name}`}
                className="absolute right-[9px] top-1/2 hidden -translate-y-1/2 items-center justify-center rounded p-1 text-text-faint transition-colors hover:text-text-secondary group-hover/pin:flex"
              >
                <X size={13} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// not drawn on any board: the design shows the pinned list but no way to add to
// it. the toggle lives in the shell so pinning costs no page code.
export function PinToggle({ experiment }: { experiment: PinnedExperiment }) {
  const { isPinned, toggle } = usePinned();
  const pinned = isPinned(experiment.id);
  const Icon = pinned ? PinOff : Pin;

  return (
    <button
      type="button"
      onClick={() => toggle(experiment)}
      aria-label={pinned ? "Unpin experiment" : "Pin experiment"}
      title={pinned ? "Unpin from sidebar" : "Pin to sidebar"}
      className={cn(
        "flex size-8 items-center justify-center rounded-[7px] transition-colors hover:bg-bg-hover",
        pinned ? "text-text-secondary" : "text-text-faint hover:text-text-dim",
      )}
    >
      <Icon size={16} />
    </button>
  );
}

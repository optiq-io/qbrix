"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@qbrix/ui/lib/utils";
import type { MenuItem } from "@qbrix/ui/next/menu";
import { StateDot, type State } from "@qbrix/ui/next/state";
import { routes } from "@/config/routes";
import { pins as pinsApi } from "@/lib/api/pins";
import { queryKeys } from "@/lib/api/query-keys";
import type { Pin } from "@/lib/api/types";
import { isNextNavActive } from "./nav";

const STATE: Record<string, State> = { live: "ok", paused: "part" };

function usePins() {
  return useQuery({
    queryKey: queryKeys.pins.all,
    queryFn: pinsApi.list,
    staleTime: 30_000,
  });
}

/** what a loop's or metric's ⋯ menu needs to pin it */
export function usePin(target: Pin): { pinned: boolean; menuItem: MenuItem } {
  const queryClient = useQueryClient();
  const { data } = usePins();
  const pinned = data?.some((pin) => pin.kind === target.kind && pin.ref === target.ref) ?? false;

  const toggle = useMutation({
    mutationFn: (next: boolean) =>
      next ? pinsApi.pin(target.kind, target.ref) : pinsApi.unpin(target.kind, target.ref),
    onMutate: async (next) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.pins.all });
      const previous = queryClient.getQueryData<Pin[]>(queryKeys.pins.all);
      const others = (previous ?? []).filter((pin) => pin.kind !== target.kind || pin.ref !== target.ref);
      queryClient.setQueryData<Pin[]>(queryKeys.pins.all, next ? [...others, target] : others);
      return { previous };
    },
    // not onError: that would replace the global toast a failed pin should show
    onSettled: (_data, error, _next, context) => {
      if (error) queryClient.setQueryData(queryKeys.pins.all, context?.previous);
      queryClient.invalidateQueries({ queryKey: queryKeys.pins.all });
    },
  });

  return {
    pinned,
    menuItem: { label: pinned ? "Unpin" : "Pin", onSelect: () => toggle.mutate(!pinned) },
  };
}

export function PinnedList({ pins, pathname }: { pins: Pin[]; pathname: string | null }) {
  if (pins.length === 0) {
    return <p className="px-2 py-1.5 n-label font-normal text-n-text-3">Pin a loop or metric from its ⋯ menu</p>;
  }

  return (
    <ul className="flex flex-col gap-0.5">
      {pins.map((pin) => {
        const href = pin.kind === "loop" ? routes.next.loop(pin.key) : routes.next.metric(pin.key);
        const state = pin.state ? STATE[pin.state] : undefined;
        const active = isNextNavActive(pathname, href);
        return (
          <li key={`${pin.kind}:${pin.ref}`}>
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-n-control px-2 py-1 n-body text-n-text-2 hover:bg-n-fill-1",
                active && "bg-n-fill-2 font-medium text-n-text-1 hover:bg-n-fill-2",
              )}
            >
              {state ? <StateDot state={state} /> : <span aria-hidden className="w-1.5 shrink-0" />}
              <span className={cn("min-w-0 truncate", pin.kind === "metric" && "font-n-mono text-[12px]")}>{pin.name}</span>
              {pin.state && pin.state !== "live" && <span className="shrink-0 n-meta text-n-text-3">· {pin.state}</span>}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function PinnedSection() {
  const pathname = usePathname();
  const { data } = usePins();

  return (
    <>
      <p className="px-2 py-1 n-label text-n-text-3">Pinned</p>
      <PinnedList pins={data ?? []} pathname={pathname} />
    </>
  );
}

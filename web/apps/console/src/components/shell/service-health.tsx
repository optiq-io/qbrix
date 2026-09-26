"use client";

import { useQuery } from "@tanstack/react-query";
import { AccentDot } from "@qbrix/ui/components/accent-dot";
import { runtime } from "@/lib/api/runtime";
import { queryKeys } from "@/lib/api/query-keys";

type ServiceStatus = "loading" | "healthy" | "unhealthy";

type HealthState = {
  redis: ServiceStatus;
  motor: ServiceStatus;
  cortex: ServiceStatus;
};

const initial: HealthState = {
  redis: "loading",
  motor: "loading",
  cortex: "loading",
};

async function fetchHealth(): Promise<HealthState> {
  const results = await Promise.allSettled([
    runtime.redisHealth(),
    runtime.motorHealth(),
    runtime.cortexHealth(),
  ]);
  const toStatus = (
    r: PromiseSettledResult<{ status: string }>,
  ): ServiceStatus => {
    if (r.status !== "fulfilled") return "unhealthy";
    return r.value.status === "healthy" ? "healthy" : "unhealthy";
  };
  return {
    redis: toStatus(results[0]),
    motor: toStatus(results[1]),
    cortex: toStatus(results[2]),
  };
}

// one poll no matter how many cards mount. the rail, the desktop panel and the
// mobile sheet all render health and all stay mounted so they can transition,
// so a per-component interval would poll three services three times over.
export function useServiceHealth(): HealthState {
  const { data } = useQuery({
    queryKey: queryKeys.runtime.all,
    queryFn: fetchHealth,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
  });
  return data ?? initial;
}

const SERVICE_NAMES = ["redis", "motor", "cortex"] as const;

function toneFor(status: ServiceStatus) {
  if (status === "healthy") return "positive" as const;
  if (status === "loading") return "faint" as const;
  return "danger" as const;
}

// board `Console Shell` / Sidebar / Health. the board draws this card and then
// disables it — but the panel *replaces* the rail at xl, so without it health
// disappears the moment you expand the sidebar. it comes back for that reason.
//
// steady state is exactly as drawn: a SERVICES label and three dots. the names
// only surface when one is down, which is the only time you need to know which
// — and it is what the card's vertical gap was left room for.
export function ServiceHealthCard() {
  const state = useServiceHealth();
  const down = SERVICE_NAMES.filter((n) => state[n] === "unhealthy");

  return (
    <div className="flex flex-col gap-[11px] rounded-[11px] border border-border-subtle bg-bg-panel px-3 py-[13px]">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] uppercase tracking-[0.145em] text-text-faint">
          Services
        </span>
        <span className="flex items-center gap-1">
          {SERVICE_NAMES.map((name) => (
            <span key={name} title={`${name}: ${state[name]}`}>
              <AccentDot
                size={6}
                tone={toneFor(state[name])}
                active={state[name] !== "loading"}
              />
            </span>
          ))}
        </span>
      </div>
      {down.length > 0 && (
        <span className="font-mono text-[10.5px] text-danger">
          {down.join(", ")} unreachable
        </span>
      )}
    </div>
  );
}

// board `Console Shell` / Rail / Health: the rail has room for one dot, so the
// three services collapse into their worst status. the expanded panel's
// three-up SERVICES card is drawn but not built.
export function ServiceHealthDot() {
  const state = useServiceHealth();
  const statuses = SERVICE_NAMES.map((n) => state[n]);
  const status: ServiceStatus = statuses.includes("unhealthy")
    ? "unhealthy"
    : statuses.includes("loading")
      ? "loading"
      : "healthy";

  const label =
    status === "loading"
      ? "checking services"
      : `redis, motor, cortex: ${status}`;

  return (
    <span
      className="flex size-[38px] items-center justify-center"
      title={label}
      aria-label={label}
    >
      <AccentDot size={8} tone={toneFor(status)} active={status !== "loading"} />
    </span>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/lib/api/query-keys";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { routes } from "@/config/routes";

export type Crumb = { label: string; href?: string };

// the experiment id out of /experiments/{id}[/tab], or null anywhere else.
// `new` is a static sibling route, not an id — without the guard the crumb read
// "new" and, worse, the query below fetched an experiment by that name on every
// visit to the creation page.
export function useExperimentId(): string | null {
  const pathname = usePathname();
  const match = pathname?.match(/^\/experiments\/([^/]+)/);
  if (!match || match[1] === "new") return null;
  return match[1];
}

// the layout for these routes already holds this exact key, so the crumb reads
// the same cache entry rather than issuing a second request
export function useCurrentExperiment() {
  const id = useExperimentId();
  const { data } = useQuery({
    queryKey: queryKeys.experiments.detail(id ?? ""),
    queryFn: () => experimentsApi.get(id as string),
    enabled: !!id,
  });
  return { id, experiment: data };
}

export function useCrumbs(): Crumb[] {
  const pathname = usePathname() ?? "/";
  const { id, experiment } = useCurrentExperiment();

  if (id) {
    // home *is* the experiments list, so an experiment hangs off Home. the
    // boards draw "Experiments / {name}" against a route that doesn't exist.
    return [
      { label: "Home", href: routes.home },
      { label: experiment?.name ?? id },
    ];
  }
  if (pathname === "/experiments/new") {
    return [{ label: "Home", href: routes.home }, { label: "New experiment" }];
  }
  if (pathname === routes.newPool) {
    return [{ label: "Pools", href: routes.pools }, { label: "New pool" }];
  }
  if (pathname.startsWith(routes.pools)) return [{ label: "Pools" }];
  if (pathname.startsWith("/developers/event-log")) {
    return [{ label: "Event log" }];
  }
  // the board draws "Settings / API keys", but the settings tab lives in
  // component state and never reaches the url — there is nothing truthful to
  // put in the leaf until it does.
  if (pathname.startsWith(routes.settings)) return [{ label: "Settings" }];
  return [{ label: "Home" }];
}

// board `Console Shell` / Topbar / Crumb: 15px throughout. the trailing crumb
// is $text-primary at 500; anything before it drops to $text-dim at 400 and
// links, with a $text-faint slash between.
export function Breadcrumb({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-[10px]">
      {crumbs.map((crumb, i) => {
        const last = i === crumbs.length - 1;
        return (
          <span key={`${crumb.label}-${i}`} className="flex min-w-0 items-center gap-[10px]">
            {i > 0 && (
              <span aria-hidden className="text-[15px] text-text-faint">
                /
              </span>
            )}
            {last || !crumb.href ? (
              <span className="truncate text-[15px] font-medium text-text-primary">
                {crumb.label}
              </span>
            ) : (
              <Link
                href={crumb.href}
                className="shrink-0 text-[15px] text-text-dim transition-colors hover:text-text-secondary"
              >
                {crumb.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}

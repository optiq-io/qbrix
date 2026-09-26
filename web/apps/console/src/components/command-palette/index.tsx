"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  FlaskConical,
  LayoutGrid,
  LogOut,
  Pause,
  Play,
  Plus,
  ScrollText,
  Search,
  Settings,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { useToast } from "@qbrix/ui/components/toast";
import { useAuth } from "@/lib/auth/context";
import { useEntitlements } from "@/lib/entitlements";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { queryKeys } from "@/lib/api/query-keys";
import { routes } from "@/config/routes";
import { useCurrentExperiment } from "@/components/shell/breadcrumb";

// board `APP · Command Palette`.

type Entry = {
  id: string;
  label: string;
  meta?: string;
  icon: LucideIcon;
  onSelect: () => void;
};

// item: 44 tall, r9, 13px gap, 12px inset. selection is the only state that
// spends colour — $bg-hover ground, accent glyph, primary label.
function PaletteEntry({ entry, onRun }: { entry: Entry; onRun: () => void }) {
  const Icon = entry.icon;
  return (
    <Command.Item
      value={`${entry.id} ${entry.label} ${entry.meta ?? ""}`}
      onSelect={() => {
        entry.onSelect();
        onRun();
      }}
      className={cn(
        "group flex h-11 cursor-pointer items-center gap-[13px] rounded-[9px] px-3 transition-colors",
        "aria-selected:bg-bg-hover",
      )}
    >
      <Icon
        size={17}
        className="shrink-0 text-text-dim group-aria-selected:text-accent"
      />
      <span className="truncate text-[15px] text-text-secondary group-aria-selected:text-text-primary">
        {entry.label}
      </span>
      {entry.meta && (
        <span className="ml-auto shrink-0 font-mono text-[12px] tracking-[0.02em] text-text-faint">
          {entry.meta}
        </span>
      )}
    </Command.Item>
  );
}

function Section({
  label,
  entries,
  onRun,
}: {
  label: string;
  entries: Entry[];
  onRun: () => void;
}) {
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-col gap-[2px] px-[10px] py-3">
      <span className="font-mono text-[11.5px] uppercase tracking-[0.14em] text-text-faint">
        {label}
      </span>
      {entries.map((entry) => (
        <PaletteEntry key={entry.id} entry={entry} onRun={onRun} />
      ))}
    </div>
  );
}

function Hint({ keys, label }: { keys: string; label: string }) {
  return (
    <span className="flex items-center gap-[7px]">
      <span className="font-mono text-[10px] tracking-[0.02em] text-text-dim">
        {keys}
      </span>
      <span className="text-[13px] text-text-faint">{label}</span>
    </span>
  );
}

export function CommandPalette() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { logout } = useAuth();
  const { gate } = useEntitlements();
  const { id: currentExperimentId, experiment: currentExperiment } =
    useCurrentExperiment();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onOpenEvent() {
      setOpen(true);
    }
    window.addEventListener("qbrix:command-palette:open", onOpenEvent);
    return () =>
      window.removeEventListener("qbrix:command-palette:open", onOpenEvent);
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    // cmdk has to mount before the input exists
    const t = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, [open]);

  // one list on open, then filtering happens here. the previous version issued
  // a `list({ search })` request per keystroke — eight requests to type
  // "checkout" — which is the backend search the ticket rules out.
  const { data: experimentList } = useQuery({
    queryKey: queryKeys.experiments.list({ limit: 200, offset: 0 }),
    queryFn: () => experimentsApi.list({ limit: 200, offset: 0 }),
    enabled: open,
    staleTime: 30_000,
  });

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      experimentsApi.update(id, { enabled }),
    onSuccess: (_data, { id, enabled }) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.experiments.detail(id),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.experiments.all });
      toast.success(enabled ? "Experiment resumed" : "Experiment paused");
    },
    onError: () => toast.error("Failed to update experiment status"),
  });

  const close = useCallback(() => setOpen(false), []);

  const go = useCallback(
    (href: string) => {
      router.push(href);
      close();
    },
    [router, close],
  );

  const needle = query.trim().toLowerCase();

  // the board draws an EXPERIMENTS group and no others, which matches what is
  // addressable: an experiment owns a route, a pool has no detail page, and a
  // gate has no identity at all — it is per-experiment config, reached through
  // the experiment's own Gate tab.
  const experimentEntries: Entry[] = needle
    ? (experimentList?.experiments ?? [])
        .filter((exp) => exp.name.toLowerCase().includes(needle))
        .slice(0, 6)
        .map((exp) => ({
          id: `experiment-${exp.id}`,
          label: exp.name,
          meta: exp.enabled ? "enabled" : "paused",
          icon: FlaskConical,
          onSelect: () => go(routes.experimentDetail(exp.id)),
        }))
    : [];

  const jumpEntries: Entry[] = [
    { id: "jump-home", label: "Home", icon: LayoutGrid, href: routes.home },
    { id: "jump-pools", label: "Pools", icon: Boxes, href: routes.pools },
    // same rule as the sidebar: shown when locked, hidden when absent
    ...(gate("event_log") !== "absent"
      ? [
          {
            id: "jump-events",
            label: "Event log",
            icon: ScrollText,
            href: routes.eventLog,
          },
        ]
      : []),
    {
      id: "jump-settings",
      label: "Settings",
      icon: Settings,
      href: routes.settings,
    },
  ].map(({ href, ...rest }) => ({ ...rest, onSelect: () => go(href) }));

  const actionEntries: Entry[] = [
    {
      id: "action-new-experiment",
      label: "Create experiment",
      icon: Plus,
      // creation is a page, so the palette only has to know a URL. it used to
      // navigate to `/?create=experiment` and rely on Home reading the param,
      // opening a dialog and stripping it again.
      onSelect: () => go(routes.newExperiment()),
    },
    {
      id: "action-new-pool",
      label: "Create pool",
      icon: Plus,
      onSelect: () => go(routes.newPool),
    },
    // contextual, exactly as the board draws it ("Pause checkout-cta")
    ...(currentExperimentId && currentExperiment
      ? [
          {
            id: "action-toggle-experiment",
            label: `${currentExperiment.enabled ? "Pause" : "Resume"} ${currentExperiment.name}`,
            icon: currentExperiment.enabled ? Pause : Play,
            onSelect: () => {
              toggle.mutate({
                id: currentExperimentId,
                enabled: !currentExperiment.enabled,
              });
              close();
            },
          },
        ]
      : []),
    {
      id: "action-sign-out",
      label: "Sign out",
      icon: LogOut,
      onSelect: () => {
        logout();
        close();
      },
    },
  ];

  const filter = (entries: Entry[]) =>
    needle
      ? entries.filter((e) => e.label.toLowerCase().includes(needle))
      : entries;

  const jump = filter(jumpEntries);
  const actions = filter(actionEntries);
  const empty =
    experimentEntries.length === 0 && jump.length === 0 && actions.length === 0;

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      className="fixed inset-0 z-50 flex items-start justify-center bg-[#050607D9] pt-[15vh]"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="mx-4 w-full max-w-[644px] overflow-hidden rounded-[18px] border border-border-strong bg-bg-overlay shadow-[0_24px_64px_#000000B3]">
        <Command
          shouldFilter={false}
          onKeyDown={(e) => {
            if (e.key === "Escape") close();
          }}
        >
          <div className="flex h-[62px] items-center gap-[14px] border-b border-border-subtle px-[22px]">
            <Search size={18} className="shrink-0 text-text-faint" />
            <Command.Input
              ref={inputRef}
              value={query}
              onValueChange={setQuery}
              placeholder="Search or jump to…"
              className="flex-1 bg-transparent text-[17px] text-text-primary outline-none placeholder:text-text-faint"
            />
            <span className="shrink-0 font-mono text-[12px] tracking-[0.02em] text-text-faint">
              ESC
            </span>
          </div>

          <Command.List className="max-h-[420px] overflow-y-auto">
            {empty && (
              <div className="px-[22px] py-8 text-center text-[14px] text-text-dim">
                No matches for “{query}”
              </div>
            )}
            <Section
              label="Experiments"
              entries={experimentEntries}
              onRun={close}
            />
            <Section label="Jump to" entries={jump} onRun={close} />
            <Section label="Actions" entries={actions} onRun={close} />
          </Command.List>

          <div className="flex h-11 items-center gap-[22px] border-t border-border-subtle px-[18px]">
            <Hint keys="↑↓" label="navigate" />
            <Hint keys="↵" label="open" />
            <Hint keys="⌘K" label="close" />
          </div>
        </Command>
      </div>
    </div>
  );
}

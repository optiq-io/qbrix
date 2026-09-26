"use client";

import { useState } from "react";
import Link from "next/link";
import { Link as LinkIcon, Monitor } from "lucide-react";
import { routes } from "@/config/routes";
import { useEntitlements } from "@/lib/entitlements";

// board `APP · Guarded route @ 390`.
//
// the responsive contract's test: if an email link or a Stripe redirect can
// land a person here on a phone, it must work on a phone. these seven routes
// fail it — they are dense tables, parameter editors and rule builders that a
// 390px column can only misrepresent — so they are guarded rather than
// squashed, and the guard's job is to get the URL to a laptop intact.
//
// this is a `lg:hidden` / `hidden lg:*` pair rather than a JS breakpoint. a
// width read during render is a hydration mismatch waiting to happen.

type GuardedSurface =
  | "experiment.arms"
  | "experiment.policy"
  | "experiment.gate"
  | "experiment.insights"
  | "experiment.activity"
  | "experiment.new"
  | "pools"
  | "settings"
  | "event-log";

// one map for all seven, the same shape as GATED_SURFACES in
// components/ee/feature-gate.tsx — the copy is reviewable in one place.
const GUARDED: Record<GuardedSurface, { title: string; description: string }> = {
  "experiment.arms": {
    title: "Variants need a wider screen",
    description:
      "Each variant is drawn against a shared reward scale, so the curves only mean something side by side. A phone would have to stack them, and stacked they compare nothing.",
  },
  "experiment.policy": {
    title: "Policy needs a wider screen",
    description:
      "Tuning a policy means editing parameters against live posteriors. We would rather send you to a laptop than give you a cramped version of it.",
  },
  "experiment.gate": {
    title: "Feature gate needs a wider screen",
    description:
      "Targeting rules are built one clause at a time, and a mis-tapped operator changes who is eligible for a live experiment. This one is deliberately desktop-only.",
  },
  "experiment.insights": {
    title: "Insights needs a wider screen",
    description:
      "Cumulative reward, traffic share and per-variant rates are read against each other across a wide plot. Narrowed to a phone they stop being comparable.",
  },
  "experiment.activity": {
    title: "Activity needs a wider screen",
    description:
      "Each row is a timestamp, a stream, an actor and a payload read across one line. Wrapped onto a phone it stops being a row, and the audit trail is the part you would be here to read.",
  },
  "experiment.new": {
    title: "Creating an experiment needs a wider screen",
    description:
      "Pool, reward type and strategy are fixed the moment it exists, and the form is built so you can see all three at once before you commit. A phone can only show them one at a time, which is the thing this replaced.",
  },
  pools: {
    title: "Pools needs a wider screen",
    description:
      "The pool list carries every variant name inline, which is what makes it scannable. At 390 it truncates to the point of being a list of pool names.",
  },
  settings: {
    title: "Settings needs a wider screen",
    description:
      "Workspace members, API keys and billing are all long-lived changes made from a table. They are safer done deliberately, on a machine with room for the table.",
  },
  "event-log": {
    title: "Event log needs a wider screen",
    description:
      "Each row is a timestamp, a category, an actor and a payload read across one line. Wrapped onto a phone the stream stops being readable at a glance.",
  },
};

// the routes that do work at 390, so the card is not a dead end. the board
// lists four; "Experiments" is not one of them here because Home *is* the
// experiment list — the /experiments route is on the never-reintroduce list.
function availableRoutes(overviewHref: string | null, hasBilling: boolean) {
  return [
    { label: "Home", href: routes.home },
    ...(overviewHref ? [{ label: "Overview", href: overviewHref }] : []),
    // without billing there is no tab to land on, so the chip would take you to
    // Settings and quietly show you Profile instead
    ...(hasBilling ? [{ label: "Billing", href: routes.settingsBilling }] : []),
  ];
}

// the wrapper each guarded page uses. the desktop tree stays in the markup and
// is hidden by CSS rather than swapped out in JS, so there is no width read
// during render and no hydration mismatch.
export function GuardedRoute({
  children,
  ...guard
}: React.ComponentProps<typeof MobileGuard> & { children: React.ReactNode }) {
  return (
    <>
      <MobileGuard {...guard} />
      <div className="hidden min-w-0 flex-1 flex-col lg:flex">{children}</div>
    </>
  );
}

export function MobileGuard({
  surface,
  backHref,
  backLabel = "Back to overview",
  /** the experiment tabs can offer their own Overview as a working route; the
      workspace-level guards have no such sibling */
  overviewHref = null,
}: {
  surface: GuardedSurface;
  backHref: string;
  backLabel?: string;
  overviewHref?: string | null;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const { title, description } = GUARDED[surface];
  const { hasBilling } = useEntitlements();
  const available = availableRoutes(overviewHref, hasBilling);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setState("copied");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      // the clipboard API is permission-gated and refuses outright on an
      // insecure origin or an unfocused document. getting the URL onto another
      // device is the only thing this card is for, so a silent no-op is not an
      // acceptable failure — fall back to showing the URL to copy by hand.
      // mobile browsers routinely collapse the address bar, so "it's up there"
      // is not an answer either.
      setState("failed");
    }
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-10 lg:hidden">
      <div className="flex w-full max-w-[342px] flex-col items-center rounded-2xl border border-border-subtle bg-bg-raised p-7">
        <div className="flex size-[52px] items-center justify-center rounded-[14px] border border-border-subtle bg-bg-panel">
          <Monitor size={23} className="text-text-dim" />
        </div>

        {/* h2, not h1 — on an experiment tab the layout's header is still
            mounted and already owns the page's h1 (the experiment name). this
            is a state within the page, the same call `EmptyState` makes. */}
        <h2 className="pt-5 text-center text-[20px] font-semibold tracking-[-0.3px] text-text-primary">
          {title}
        </h2>
        <p className="pt-2.5 text-center text-[14.5px] leading-[1.5] text-text-dim">
          {description}
        </p>

        <button
          type="button"
          onClick={copyLink}
          className="mt-[22px] flex h-[46px] w-full items-center justify-center gap-2 rounded-[23px] bg-accent transition-colors hover:bg-accent/90"
        >
          <LinkIcon size={15} className="text-bg" />
          <span className="text-[15px] font-semibold text-bg">
            {state === "copied" ? "Copied" : "Copy link"}
          </span>
        </button>

        {state === "failed" && (
          <p className="mt-2.5 w-full select-all break-all rounded-lg border border-border-subtle bg-bg-panel px-3 py-2 text-center font-mono text-[12px] text-text-secondary">
            {typeof window === "undefined" ? "" : window.location.href}
          </p>
        )}

        <Link
          href={backHref}
          className="mt-2.5 flex h-[46px] w-full items-center justify-center rounded-[23px] border border-border-strong text-[15px] font-medium text-text-primary transition-colors hover:border-border-strong/70"
        >
          {backLabel}
        </Link>
      </div>

      <div className="flex w-full max-w-[342px] flex-col items-center gap-2.5 pt-6">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.145em] text-text-faint">
          Available on mobile
        </span>
        <div className="flex flex-wrap justify-center gap-2">
          {available.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className="rounded-[14px] border border-border-subtle px-[11px] py-1.5 text-[12.5px] text-text-dim transition-colors hover:text-text-secondary"
            >
              {item.label}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}

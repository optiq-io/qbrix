import { Fragment } from "react";
import Link from "next/link";
import { ChevronRight, Eye } from "lucide-react";
import { cn } from "../lib/utils";
import { StateDot, type State } from "./state";

export type Crumb = { label: string; href?: string };
export type ObjectTab = { key: string; label: string; count?: number; href: string };

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-n-ink";

export function ObjectPage({
  crumbs,
  actions,
  menu,
  viewOnly,
  tabs,
  activeTab,
  rail,
  staged,
  canEdit = true,
  className,
  children,
}: {
  crumbs: Crumb[];
  actions?: React.ReactNode;
  /** the ⋯ menu; its items carry their own canEdit, so it stays for a viewer */
  menu?: React.ReactNode;
  /** who a viewer can ask: "Ask Ada or Mustafa to change this loop" */
  viewOnly?: string;
  tabs?: ObjectTab[];
  activeTab?: string;
  rail: React.ReactNode;
  /** the staged bar: above the tabs, because it collects edits from all of them */
  staged?: React.ReactNode;
  /** false for a person who can't change this object: actions are absent, never disabled */
  canEdit?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-1 flex-col bg-n-surface", className)}>
      <header className="flex h-[52px] shrink-0 items-center gap-2 border-b border-n-line-2 px-6">
        <nav aria-label="Breadcrumb" className="n-body flex min-w-0 items-center gap-2">
          {crumbs.map((crumb, at) => {
            const last = at === crumbs.length - 1;
            return (
              <Fragment key={crumb.label}>
                {at > 0 && <ChevronRight size={13} className="shrink-0 text-n-text-3" />}
                {crumb.href && !last ? (
                  <Link href={crumb.href} className={cn("shrink-0 text-n-text-3 hover:text-n-text-1", FOCUS)}>
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current={last ? "page" : undefined} className={cn("truncate", last ? "text-n-text-1" : "text-n-text-3")}>
                    {crumb.label}
                  </span>
                )}
              </Fragment>
            );
          })}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {canEdit ? actions : viewOnly && <ViewOnly who={viewOnly} />}
          {menu}
        </div>
      </header>

      {staged}

      {tabs && tabs.length > 0 && (
        <nav aria-label="Sections" className="flex h-[42px] shrink-0 gap-6 border-b border-n-line-2 px-6">
          {tabs.map((tab) => {
            const active = tab.key === activeTab;
            return (
              <Link
                key={tab.key}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "n-body -mb-px flex items-center gap-1 border-b",
                  FOCUS,
                  active ? "border-n-ink font-medium text-n-text-1" : "border-transparent text-n-text-2 hover:text-n-text-1",
                )}
              >
                {tab.label}
                {tab.count !== undefined && <span className="n-label font-normal tabular-nums text-n-text-3">{tab.count}</span>}
              </Link>
            );
          })}
        </nav>
      )}

      <div className="flex flex-1">
        <div className="min-w-0 flex-1 px-6 py-8">{children}</div>
        <aside className="w-[300px] shrink-0 border-l border-n-line-2 bg-n-bg">
          <div className="sticky top-0 flex h-full max-h-screen flex-col gap-6 overflow-y-auto px-6 py-8">{rail}</div>
        </aside>
      </div>
    </div>
  );
}

function ViewOnly({ who }: { who: string }) {
  return (
    <>
      <span className="n-meta inline-flex h-6 items-center gap-1.5 rounded-n-control bg-n-fill-2 px-2 font-medium text-n-text-2">
        <Eye size={13} className="text-n-text-3" />
        View only
      </span>
      <span className="n-meta text-n-text-3">{who}</span>
    </>
  );
}

export function RailSection({
  title,
  className,
  children,
}: {
  title: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("flex flex-col gap-3", className)}>
      <h2 className="n-meta font-medium text-n-text-3">{title}</h2>
      {children}
    </section>
  );
}

export function Property({ label, value, state }: { label: string; value: React.ReactNode; state?: State }) {
  return (
    <div className="n-body flex items-center gap-2">
      <span className="shrink-0 text-n-text-3">{label}</span>
      <span className="ml-auto flex min-w-0 items-center gap-2">
        {state && <StateDot state={state} />}
        <span className="truncate text-n-text-1">{value}</span>
      </span>
    </div>
  );
}

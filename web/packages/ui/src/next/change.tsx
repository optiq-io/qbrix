"use client";

import Link from "next/link";
import { Check, ChevronRight, Undo2 } from "lucide-react";
import { cn } from "../lib/utils";
import { Button } from "./button";
import { ActorMark, LoopRef, MetricRef, actorName, type Actor } from "./entity";
import { PHONE_BAR } from "./sheet";
import { StateBadge, type State } from "./state";

export type ChangeLayout = "inbox" | "history" | "phone";

/** how far below a history row's top its first line starts, for placing it on the time rail */
export const HISTORY_LINE_INSET = 11;

export type ChangeTarget = { kind: "loop" | "metric" | "other"; name: string; href?: string };

export type ChangeDiff = { field: string; before?: string; after?: string };

export type ChangeData = {
  actor: Actor;
  /** one verb per kind of change: "renamed", "proposes a change to" */
  verb: string;
  target: ChangeTarget;
  diff?: ChangeDiff[];
  reason?: string;
  consequence?: string;
  proposed?: boolean;
  status?: { state: State; label: string };
  /** where it came from when no connection says so: "safety pause" */
  context?: string;
  /** already formatted, a time or a range: "14:02", "11:20 to 11:28" */
  time: string;
  /** why it can no longer be undone: "Undone by Mustafa", "Moved since" with a link to the later change */
  tag?: { label: string; href?: string };
};

export type ChangeActions = {
  /** the label names the consequence: "Approve and start cycle 3" */
  approve?: { label: string; onSelect: () => void };
  askForChanges?: () => void;
  decline?: () => void;
  undo?: () => void;
};

export type ChangeFold = { label: string; expanded: boolean; onToggle: () => void };

export type ChangeProps = {
  change: ChangeData;
  layout: ChangeLayout;
  actions?: ChangeActions;
  /** false for a person who can't act on it: its actions are absent, never disabled */
  canEdit?: boolean;
  selected?: boolean;
  onSelect?: () => void;
  fold?: ChangeFold;
  /** the screen's own evidence, between the reason and the consequence: now and after, the new option */
  children?: React.ReactNode;
  /** below the actions: the thread, raising the connection's level */
  after?: React.ReactNode;
  className?: string;
};

export function Change({ layout, ...props }: ChangeProps) {
  if (layout === "history") return <HistoryRow {...props} />;
  return <ChangePage phone={layout === "phone"} {...props} />;
}

function Target({ target }: { target: ChangeTarget }) {
  if (target.kind === "loop") return <LoopRef name={target.name} href={target.href} />;
  if (target.kind === "metric") return <MetricRef name={target.name} href={target.href} />;
  return <span className="font-medium text-n-text-1">{target.name}</span>;
}

function Sentence({ change }: { change: ChangeData }) {
  return (
    <>
      <span className="font-medium text-n-text-1">{actorName(change.actor)}</span>{" "}
      <span className="text-n-text-2">{change.verb}</span> <Target target={change.target} />
      <span className="text-n-text-2">.</span>
    </>
  );
}

function through(actor: Actor) {
  if (actor.kind === "connection") return `for ${actor.onBehalfOf}, through ${actor.name}`;
  if (actor.kind === "member" && actor.via) return `through ${actor.via}`;
  return undefined;
}

export function DiffChip({ field, before, after, className }: ChangeDiff & { className?: string }) {
  const value = "min-w-0 truncate";
  return (
    <span
      className={cn(
        "n-label inline-flex max-w-full items-center gap-1.5 rounded-n-chip border border-n-line px-1.5 py-0.5 font-n-mono font-normal",
        className,
      )}
    >
      <span className="shrink-0 text-n-text-3">{field}</span>
      {before !== undefined && after !== undefined ? (
        <>
          <span className={cn(value, "text-n-text-2")}>{before}</span>
          <span aria-hidden className="shrink-0 font-n-sans text-n-text-3">
            →
          </span>
          <span className="sr-only">to</span>
          <span className={cn(value, "text-n-text-1")}>{after}</span>
        </>
      ) : after !== undefined ? (
        <span className={cn(value, "text-n-text-1")}>+ {after}</span>
      ) : (
        <span className={cn(value, "text-n-text-2")}>− {before}</span>
      )}
    </span>
  );
}

function Diff({ diff }: { diff?: ChangeDiff[] }) {
  if (!diff?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {diff.map((entry) => (
        <DiffChip key={entry.field} {...entry} />
      ))}
    </div>
  );
}

function Tag({ label, href }: { label: string; href?: string }) {
  const className =
    "n-label inline-flex h-[22px] shrink-0 items-center rounded-n-chip bg-n-fill-2 px-1.5 font-normal text-n-text-2";
  if (!href) return <span className={className}>{label}</span>;
  return (
    <Link href={href} className={cn(className, "relative z-10 hover:text-n-text-1")}>
      {label}
    </Link>
  );
}

function HistoryRow({ change, actions, canEdit = true, selected, onSelect, fold, className }: Omit<ChangeProps, "layout">) {
  const meta = [change.target.name, through(change.actor), change.context, change.time].filter(Boolean).join("  ·  ");
  const undo = canEdit && !change.tag ? actions?.undo : undefined;

  return (
    <article
      className={cn(
        "relative flex gap-3 rounded-n-control border border-transparent px-3 py-2.5 transition-colors",
        onSelect && !selected && "hover:bg-n-fill-1",
        selected && "border-n-line bg-n-fill-1",
        className,
      )}
    >
      {onSelect && (
        <button
          type="button"
          aria-label={`${actorName(change.actor)} ${change.verb} ${change.target.name}`}
          aria-pressed={selected}
          onClick={onSelect}
          className="absolute inset-0 rounded-n-control focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-n-ink"
        />
      )}
      <ActorMark actor={change.actor} />
      <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
        <p className="n-body">
          <Sentence change={change} />
        </p>
        <Diff diff={change.diff} />
        <p className="n-meta text-n-text-3">{meta}</p>
        {change.reason && <p className="n-meta text-n-text-2">“{change.reason}”</p>}
        {change.consequence && <p className="n-meta text-n-text-3">{change.consequence}</p>}
        {fold && (
          <button
            type="button"
            aria-expanded={fold.expanded}
            onClick={fold.onToggle}
            className="n-meta relative z-10 flex items-center gap-1 self-start pt-0.5 text-n-text-2 hover:text-n-text-1"
          >
            <ChevronRight size={12} className={cn("text-n-text-3 transition-transform", fold.expanded && "rotate-90")} />
            {fold.label}
          </button>
        )}
      </div>
      {change.tag && <Tag {...change.tag} />}
      {undo && (
        <Button variant="secondary" size="sm" onClick={undo} className="relative z-10">
          <Undo2 size={12} className="text-n-text-2" />
          Undo
        </Button>
      )}
    </article>
  );
}

function ChangePage({
  change,
  phone,
  actions,
  canEdit = true,
  after,
  className,
  children,
}: Omit<ChangeProps, "layout"> & { phone: boolean }) {
  const eyebrow = [change.context, change.time].filter(Boolean).join(" · ");
  const hasActions = canEdit && actions && Object.values(actions).some(Boolean);

  return (
    <article className={cn("flex flex-col", phone && "min-h-full", className)}>
      <div className={cn("flex flex-1 flex-col", phone ? "gap-5 px-4 pb-4 pt-2" : "gap-5")}>
        <div className="flex flex-wrap items-center gap-2">
          {change.status && <StateBadge state={change.status.state}>{change.status.label}</StateBadge>}
          <span className="n-label font-normal text-n-text-3">{eyebrow}</span>
        </div>
        <h2 className={phone ? "text-[22px] font-normal leading-[1.3]" : "n-lead"}>
          <Sentence change={change} />
        </h2>
        <Diff diff={change.diff} />
        <Who change={change} phone={phone} />
        {change.reason && <Reason change={change} phone={phone} />}
        {children}
        {change.consequence && <p className="n-body text-n-text-3">{change.consequence}</p>}
        {change.tag && <Tag {...change.tag} />}
        {!phone && hasActions && <DeskActions actions={actions} />}
        {after}
      </div>
      {phone && hasActions && <PhoneActions actions={actions} />}
    </article>
  );
}

function Who({ change, phone }: { change: ChangeData; phone: boolean }) {
  const { actor, proposed } = change;
  const size = phone ? "n-body" : "n-support";

  if (actor.kind === "connection") {
    const person: Actor = { kind: "member", name: actor.onBehalfOf };
    return (
      <p className={cn(size, "text-n-text-2")}>
        {proposed ? "Asked by" : "For"}{" "}
        <ActorMark actor={person} size={16} className="mr-1 align-[2px]" />
        <span className="font-medium text-n-text-1">{actor.onBehalfOf}</span> {proposed ? "in" : "through"} {actor.name}.
        {proposed && " Nothing changes until you approve."}
      </p>
    );
  }
  if (proposed) return <p className={cn(size, "text-n-text-2")}>Nothing changes until you approve.</p>;
  return null;
}

function Reason({ change, phone }: { change: ChangeData; phone: boolean }) {
  return (
    <blockquote className="flex flex-col gap-1 border-l border-n-line pl-3">
      <p className={phone ? "text-[14px] leading-[1.5] text-n-text-2" : "n-body text-n-text-2"}>{change.reason}</p>
      {!phone && <cite className="n-label font-normal not-italic text-n-text-3">{actorName(change.actor)}&apos;s reason</cite>}
    </blockquote>
  );
}

function DeskActions({ actions }: { actions: ChangeActions }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {actions.approve && (
        <Button onClick={actions.approve.onSelect}>
          <Check size={13} />
          {actions.approve.label}
        </Button>
      )}
      {actions.askForChanges && (
        <Button variant="secondary" onClick={actions.askForChanges}>
          Ask for changes
        </Button>
      )}
      {actions.decline && (
        <Button variant="secondary" onClick={actions.decline}>
          Decline
        </Button>
      )}
      {actions.undo && (
        <Button variant="secondary" onClick={actions.undo}>
          <Undo2 size={13} className="text-n-text-2" />
          Undo
        </Button>
      )}
    </div>
  );
}

function PhoneActions({ actions }: { actions: ChangeActions }) {
  return (
    <div className={PHONE_BAR}>
      {actions.approve && (
        <Button size="lg" onClick={actions.approve.onSelect} className="h-12">
          <Check size={16} />
          {actions.approve.label}
        </Button>
      )}
      {(actions.askForChanges || actions.decline) && (
        <div className="flex gap-2.5 *:flex-1">
          {actions.askForChanges && (
            <Button variant="secondary" size="lg" onClick={actions.askForChanges}>
              Ask for changes
            </Button>
          )}
          {actions.decline && (
            <Button variant="secondary" size="lg" onClick={actions.decline}>
              Decline
            </Button>
          )}
        </div>
      )}
      {actions.undo && (
        <Button variant="secondary" size="lg" onClick={actions.undo}>
          <Undo2 size={16} className="text-n-text-2" />
          Undo
        </Button>
      )}
    </div>
  );
}

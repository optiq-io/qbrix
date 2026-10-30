import Link from "next/link";
import { Bot, GitPullRequest } from "lucide-react";
import { cn } from "../lib/utils";

function Ref({ href, className, children }: { href?: string; className: string; children: React.ReactNode }) {
  if (!href) return <span className={className}>{children}</span>;
  return (
    <Link href={href} className={cn(className, "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-n-ink")}>
      {children}
    </Link>
  );
}

export function LoopRef({ name, href, className }: { name: string; href?: string; className?: string }) {
  return (
    <Ref href={href} className={cn("font-medium text-n-text-1", href && "underline-offset-2 hover:underline", className)}>
      {name}
    </Ref>
  );
}

export type OptionTone = "ink" | "viz-2" | "viz-3" | "viz-track";

const TONE: Record<OptionTone, string> = {
  ink: "bg-n-ink",
  "viz-2": "bg-n-viz-2",
  "viz-3": "bg-n-viz-3",
  "viz-track": "bg-n-viz-track",
};

/** the chart ramp by share rank: the lead, the second, then the third and "others" together */
export function optionTone(rank?: number): OptionTone {
  if (rank === undefined) return "viz-track";
  if (rank === 0) return "ink";
  return rank === 1 ? "viz-2" : "viz-3";
}

export function OptionPill({ name, rank, className }: { name: string; rank?: number; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-[5px] rounded-n-chip border border-n-line bg-n-fill-1 px-1.5 font-medium text-n-text-1",
        className,
      )}
    >
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-[2px]", TONE[optionTone(rank)])} />
      {name}
    </span>
  );
}

export function MetricRef({ name, href, className }: { name: string; href?: string; className?: string }) {
  return (
    <Ref
      href={href}
      className={cn("font-n-mono text-n-text-1 underline decoration-n-text-3 decoration-dotted underline-offset-[3px]", className)}
    >
      {name}
    </Ref>
  );
}

export type Actor =
  | { kind: "member"; name: string; via?: string }
  | { kind: "connection"; name: string; onBehalfOf: string }
  | { kind: "qbrix" }
  | { kind: "github"; name?: string };

export function actorName(actor: Actor) {
  if (actor.kind === "qbrix") return "qbrix";
  if (actor.kind === "github") return actor.name ?? "GitHub";
  return actor.name;
}

export function ActorMark({ actor, size = 24, className }: { actor: Actor; size?: 16 | 20 | 24; className?: string }) {
  const icon = size === 24 ? 14 : size === 20 ? 12 : 10;
  return (
    <span
      aria-hidden
      style={{ width: size, height: size }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center",
        actor.kind === "member" ? "rounded-full" : "rounded-n-control",
        actor.kind === "qbrix" ? "bg-n-ink" : "bg-n-fill-2 text-n-text-2",
        className,
      )}
    >
      {actor.kind === "member" && (
        <span className="font-semibold leading-none" style={{ fontSize: size === 16 ? 9 : 11 }}>
          {actor.name.charAt(0).toUpperCase()}
        </span>
      )}
      {actor.kind === "connection" && <Bot size={icon} />}
      {actor.kind === "github" && <GitPullRequest size={icon} />}
      {actor.kind === "qbrix" && (
        <span className="rounded-full border-[1.5px] border-n-on-ink" style={{ width: size / 3, height: size / 3 }} />
      )}
    </span>
  );
}

export function ActorRef({
  actor,
  size = 16,
  withVia = false,
  className,
}: {
  actor: Actor;
  size?: 16 | 20 | 24;
  /** "Mustafa via Claude Code": who it acted for, then what it came through */
  withVia?: boolean;
  className?: string;
}) {
  const through = !withVia ? null : actor.kind === "connection" ? actor.name : actor.kind === "member" ? actor.via : null;
  const name = through && actor.kind === "connection" ? actor.onBehalfOf : actorName(actor);

  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <ActorMark actor={actor} size={size} />
      <span className="font-medium text-n-text-1">{name}</span>
      {through && <span className="text-n-text-2">via {through}</span>}
    </span>
  );
}

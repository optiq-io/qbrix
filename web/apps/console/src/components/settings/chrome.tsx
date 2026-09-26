import type { ReactNode } from "react";
import { cn } from "@qbrix/ui/lib/utils";

// the chrome every settings tab shares. boards `APP · Settings / Profile`,
// `/ Workspace`, `/ Members` and `/ API Keys` all open with the same heading
// band, and the three that carry account facts draw the same mono strip under
// it — five hand-rolled copies of one band is how they drift apart.

export function SettingsHead({
  title,
  description,
  meta,
}: {
  title: string;
  description: ReactNode;
  /** right-aligned readout: the plan, the seat count, who you are */
  meta?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-5 border-b border-border-subtle px-7 py-5">
      <div className="flex min-w-0 flex-1 flex-col gap-[7px]">
        <h2 className="text-[17px] font-semibold tracking-[-0.3px] text-text-primary">
          {title}
        </h2>
        <p className="max-w-[660px] text-[14px] leading-[1.55] text-text-dim">
          {description}
        </p>
      </div>

      {meta && (
        <div className="flex shrink-0 flex-col items-end gap-1.5 pt-1">
          {meta}
        </div>
      )}
    </div>
  );
}

export function FactStrip({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-5 border-b border-border-subtle px-7 py-[17px]">
      {children}
    </div>
  );
}

// mono per foundation rule 04 — a role, a tier and a status are all typed
// values, not prose.
export function Fact({
  label,
  value,
  sub,
}: {
  label: string;
  value: ReactNode;
  /** the cap a count runs against — "of 3"; absent when unlimited */
  sub?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-[9px]">
      <span className="font-mono text-[11px] uppercase tracking-[0.145em] text-text-faint">
        {label}
      </span>
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate font-mono text-[14.5px] tracking-[0.2px] text-text-primary">
          {value}
        </span>
        {sub && (
          <span className="shrink-0 text-[12.5px] text-text-faint">{sub}</span>
        )}
      </div>
    </div>
  );
}

// the settings equivalent of `ParamField` on the Policy tab: a 300px label
// column carrying the explanation, and the control on the right.
export function FieldRow({
  label,
  description,
  tone = "default",
  children,
}: {
  label: string;
  description: ReactNode;
  tone?: "default" | "danger";
  children: ReactNode;
}) {
  return (
    <div className="flex gap-8 border-b border-border-subtle px-7 py-6">
      <div className="flex w-[300px] shrink-0 flex-col gap-1.5">
        <span
          className={cn(
            "text-[15px] font-medium",
            tone === "danger" ? "text-danger" : "text-text-primary",
          )}
        >
          {label}
        </span>
        <p className="text-[13.5px] leading-[1.5] text-text-faint">
          {description}
        </p>
      </div>

      {/* top-aligned like ParamField: a long description makes a tall row and
          the control stays level with the label's first line */}
      <div className="flex min-w-0 flex-1 flex-col items-start gap-2.5">
        {children}
      </div>
    </div>
  );
}

// a heading for a second list inside one tab — Members' pending invites. lower
// in the hierarchy than SettingsHead, so 15px beside its explanation rather
// than a 17px block with a paragraph under it.
export function SubHead({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border-subtle px-7 py-[15px]">
      <span className="text-[15px] font-medium text-text-primary">{title}</span>
      <span className="text-[13.5px] text-text-faint">{description}</span>
    </div>
  );
}

export function Chip({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "accent" | "amber";
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center rounded-xl border px-2.5 text-[12.5px]",
        tone === "accent"
          ? "border-accent-dim bg-accent-soft text-accent"
          : tone === "amber"
            ? "border-amber/20 bg-amber/10 text-amber"
            : "border-border-subtle bg-white/[0.03] text-text-dim",
      )}
    >
      {children}
    </span>
  );
}

export const fieldInput =
  "h-10 w-[320px] max-w-full rounded-[10px] border border-border bg-bg-panel px-3.5 text-[14.5px] text-text-primary outline-none transition-colors placeholder:text-text-faint focus:border-border-strong disabled:opacity-60";

export const btnPrimary =
  "flex h-9 shrink-0 items-center gap-2 rounded-full bg-accent px-4 text-[14.5px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-40";

export const btnSecondary =
  "flex h-9 shrink-0 items-center gap-2 rounded-full border border-border-strong bg-bg-panel px-4 text-[14.5px] font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40";

export const btnDanger =
  "flex h-9 shrink-0 items-center gap-2 rounded-full border border-danger/35 bg-bg-panel px-4 text-[14.5px] font-medium text-danger transition-colors hover:bg-danger/10 disabled:opacity-40";

// the v3 pages carry the en-GB form; `formatDate` in @qbrix/ui is en-US
export function formatDay(seconds: number | undefined | null): string {
  if (!seconds) return "—";
  const d = new Date(seconds * 1000);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** "of 3", or nothing when the limit is the `-1` unlimited sentinel */
export function capLabel(cap: number | undefined): string | undefined {
  if (cap === undefined || cap === -1) return undefined;
  return `of ${cap}`;
}

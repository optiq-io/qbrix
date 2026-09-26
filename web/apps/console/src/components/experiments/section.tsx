"use client";

import { ChevronDown } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";

// board `APP · New experiment · ALT A — One page`.
//
// a numbered section of the creation form. sections 3 and 4 open collapsed:
// they have working defaults and most experiments never touch them. collapsed
// is not hidden — the head still states the decision the section holds, because
// three of the four are irreversible and none of them should be findable only
// by expanding something.

export function Section({
  step,
  title,
  summary,
  collapsible = false,
  open = true,
  onToggle,
  aside,
  children,
}: {
  step: number;
  title: string;
  /** what the section currently amounts to, shown whether open or closed */
  summary?: React.ReactNode;
  collapsible?: boolean;
  open?: boolean;
  onToggle?: () => void;
  /** a control that belongs on the head row itself, e.g. the gate's switch */
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  const head = (
    <>
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-bg-hover font-mono text-[11px] text-text-dim">
        {step}
      </span>
      <span className="shrink-0 text-[14px] font-medium text-text-primary">
        {title}
      </span>
      {summary ? (
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-text-faint">
          {summary}
        </span>
      ) : (
        <span className="flex-1" />
      )}
    </>
  );

  // the head is a row of siblings, not one big button: the gate's switch lives
  // here too, and a <button> inside a <button> is invalid html — it hydrates
  // wrong and the inner control stops being reachable.
  return (
    <section className="flex flex-col rounded-[12px] border border-border-subtle bg-bg-raised">
      <div
        className={cn(
          "flex w-full items-center gap-[10px] px-4 pt-4",
          open ? "pb-3" : "pb-4",
        )}
      >
        {collapsible ? (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            className="flex min-w-0 flex-1 items-center gap-[10px] text-left"
          >
            {head}
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 items-center gap-[10px]">{head}</div>
        )}

        {aside}

        {collapsible && (
          <button
            type="button"
            onClick={onToggle}
            aria-label={`${open ? "Collapse" : "Expand"} ${title}`}
            className="shrink-0 text-text-dim transition-colors hover:text-text-primary"
          >
            <ChevronDown
              size={15}
              className={cn("transition-transform", !open && "-rotate-90")}
            />
          </button>
        )}
      </div>

      {open && <div className="flex flex-col gap-3 px-4 pb-4">{children}</div>}
    </section>
  );
}

export function FieldRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-[96px] shrink-0 text-[13px] text-text-dim">{label}</span>
      {children}
    </div>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  autoFocus,
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <input
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      autoFocus={autoFocus}
      className={cn(
        "min-w-0 flex-1 rounded-[9px] border border-border bg-bg-panel px-3 py-[9px] text-[13.5px] text-text-primary outline-none transition-colors placeholder:text-text-faint focus:border-border-strong",
        className,
      )}
      {...rest}
    />
  );
}

/** the selectable card the boards use for reward types and strategies */
export function ChoiceCard({
  title,
  hint,
  badge,
  selected,
  onSelect,
  className,
}: {
  title: string;
  hint: string;
  badge?: string;
  selected: boolean;
  onSelect: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "flex min-w-0 flex-1 items-center gap-3 rounded-[9px] border px-3 py-[10px] text-left transition-colors",
        selected
          ? "border-accent-dim bg-accent-soft"
          : "border-border bg-bg-panel hover:border-border-strong",
        className,
      )}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-[2px]">
        <span
          className={cn(
            "truncate text-[13px] font-medium",
            selected ? "text-accent" : "text-text-primary",
          )}
        >
          {title}
        </span>
        <span className="truncate text-[11.5px] text-text-faint">{hint}</span>
      </span>
      {badge && (
        <span className="shrink-0 rounded-[6px] bg-bg-hover px-2 py-[3px] font-mono text-[11px] text-text-dim">
          {badge}
        </span>
      )}
    </button>
  );
}

export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={cn(
        "relative h-[19px] w-[34px] shrink-0 rounded-full transition-colors",
        checked ? "bg-accent" : "bg-bg-hover",
      )}
    >
      <span
        className={cn(
          "absolute top-[2px] size-[15px] rounded-full transition-all",
          checked ? "left-[17px] bg-bg" : "left-[2px] bg-text-faint",
        )}
      />
    </button>
  );
}

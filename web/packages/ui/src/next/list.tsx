"use client";

import { useId } from "react";
import Link from "next/link";
import { Check, ChevronDown } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";
import { PANEL } from "./overlay";
import { usePopover } from "./popover";

export type ListColumn<T> = {
  key: string;
  label: string;
  /** a grid track such as "150px"; columns without one share what is left */
  width?: string;
  render: (item: T) => React.ReactNode;
};

export type ListGroup<T> = { key: string; label: string; count?: number; items: T[] };

type Source<T> = { items: T[]; groups?: never } | { groups: ListGroup<T>[]; items?: never };

type Rows<T> =
  | {
      columns: ListColumn<T>[];
      rowLabel: (item: T) => string;
      href?: (item: T) => string;
      onSelect?: (item: T) => void;
      selected?: (item: T) => boolean;
      renderRow?: never;
    }
  | {
      renderRow: (item: T) => React.ReactNode;
      columns?: never;
      rowLabel?: never;
      href?: never;
      onSelect?: never;
      selected?: never;
    };

export type ListProps<T> = Source<T> &
  Rows<T> & {
    rowKey: (item: T) => string;
    /** filters and ordering; what they mean stays with the screen, which passes rows already arranged */
    controls?: React.ReactNode;
    actions?: React.ReactNode;
    /** false for a person who can't make changes: actions are absent, never disabled */
    canEdit?: boolean;
    empty?: React.ReactNode;
    className?: string;
  };

const STRETCHED =
  "absolute inset-0 rounded-n-control focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-n-ink";
const ABOVE_ROW = "min-w-0 [&_a]:relative [&_a]:z-10 [&_button]:relative [&_button]:z-10";

export function List<T>(props: ListProps<T>) {
  const { rowKey, controls, actions, canEdit = true, empty, className } = props;
  const groups: ListGroup<T>[] = props.groups ?? [{ key: "", label: "", items: props.items }];
  const hasRows = groups.some((group) => group.items.length > 0);
  const columns = props.columns;
  const template = columns?.map((column) => column.width ?? "minmax(0, 1fr)").join(" ");

  const row = (item: T) => {
    if (props.renderRow) return <li key={rowKey(item)}>{props.renderRow(item)}</li>;
    const label = props.rowLabel(item);
    const selected = props.selected?.(item);
    return (
      <div
        key={rowKey(item)}
        role="row"
        aria-selected={selected}
        style={{ gridTemplateColumns: template }}
        className={cn(
          "relative grid items-center gap-6 border-b border-n-line-2 py-3 transition-colors",
          (props.href || props.onSelect) && "hover:bg-n-fill-1",
          selected && "bg-n-fill-1",
        )}
      >
        {(props.href || props.onSelect) && (
          <div role="cell" className="contents">
            {props.href ? (
              <Link href={props.href(item)} aria-label={label} className={STRETCHED} />
            ) : (
              <button type="button" aria-label={label} onClick={() => props.onSelect?.(item)} className={STRETCHED} />
            )}
          </div>
        )}
        {props.columns.map((column) => (
          <div key={column.key} role="cell" className={ABOVE_ROW}>
            {column.render(item)}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      {(controls || (canEdit && actions)) && (
        <div className="flex flex-wrap items-center gap-2">
          {controls}
          {canEdit && actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
        </div>
      )}

      {!hasRows ? (
        empty
      ) : columns ? (
        <div role="table">
          <div role="row" style={{ gridTemplateColumns: template }} className="grid gap-6 border-b border-n-line-2 pb-2">
            {columns.map((column) => (
              <span key={column.key} role="columnheader" className="n-meta text-n-text-3">
                {column.label}
              </span>
            ))}
          </div>
          {groups.map((group) => (
            <div key={group.key} role="rowgroup" aria-label={group.label || undefined}>
              {group.label && (
                <div className="flex items-center gap-2 pb-1 pt-4">
                  <span className="n-meta font-semibold text-n-text-1">{group.label}</span>
                  {group.count !== undefined && <span className="n-label font-normal tabular-nums text-n-text-3">{group.count}</span>}
                </div>
              )}
              {group.items.map(row)}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {groups.map((group) => (
            <section key={group.key} className="flex flex-col gap-0.5">
              {group.label && <h3 className="n-label text-n-text-3">{group.label}</h3>}
              <ul className="flex flex-col gap-0.5">{group.items.map(row)}</ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

const CHIP =
  "n-meta inline-flex h-6 items-center gap-1.5 rounded-n-control border border-n-line px-2 transition-colors hover:bg-n-fill-1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-n-ink";

export function FilterChoice<T extends string>({
  label,
  icon: Icon,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  icon?: LucideIcon;
  value: T | null;
  options: { value: T; label: string; count?: number }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  const { open, setOpen, close, wrapperRef, triggerRef, contentRef, onContentKeyDown, onTriggerKeyDown } =
    usePopover("option");
  const id = useId();
  const selected = options.find((option) => option.value === value);

  return (
    <div ref={wrapperRef} className={cn("relative inline-flex", className)}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`${label}: ${selected?.label ?? "any"}`}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
        className={cn(CHIP, "text-n-text-2")}
      >
        {Icon && <Icon size={13} className="text-n-text-3" />}
        {selected?.label ?? label}
        <ChevronDown size={12} className="text-n-text-3" />
      </button>

      {open && (
        <div
          ref={contentRef}
          id={id}
          role="listbox"
          aria-label={label}
          onKeyDown={onContentKeyDown}
          className={cn(
            PANEL,
            "absolute left-0 top-[calc(100%+4px)] z-30 flex max-h-72 min-w-44 flex-col overflow-y-auto p-1 shadow-[0_8px_24px_#0000001f]",
          )}
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              tabIndex={-1}
              onClick={() => {
                close();
                onChange(option.value);
              }}
              className="n-body flex w-full items-center gap-2 rounded-n-chip px-2.5 py-1.5 text-left text-n-text-1 outline-none hover:bg-n-fill-1 focus:bg-n-fill-1"
            >
              <span className="min-w-0 flex-1 truncate">{option.label}</span>
              {option.count !== undefined && <span className="n-label font-normal tabular-nums text-n-text-3">{option.count}</span>}
              {option.value === value && <Check size={14} className="shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function FilterToggle({
  label,
  icon: Icon,
  pressed,
  onChange,
  className,
}: {
  label: string;
  icon?: LucideIcon;
  pressed: boolean;
  onChange: (pressed: boolean) => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onChange(!pressed)}
      className={cn(CHIP, pressed ? "bg-n-fill-2 text-n-text-1" : "text-n-text-2", className)}
    >
      {Icon && <Icon size={13} className="text-n-text-3" />}
      {label}
    </button>
  );
}

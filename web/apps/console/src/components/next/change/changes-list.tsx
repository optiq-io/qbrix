"use client";

import { Box, Tag, Target, Undo2 } from "lucide-react";
import { Button } from "@qbrix/ui/next/button";
import { Change } from "@qbrix/ui/next/change";
import { FilterChoice, FilterToggle, List } from "@qbrix/ui/next/list";
import { Segmented } from "@qbrix/ui/next/segmented";
import type { ChangeCounts } from "@/lib/api/types";
import { whoCounts } from "@/lib/change/eyebrow";
import { CHANGE_KINDS, NO_FILTERS, noneMatch, type ChangeFilters, type ChangeWho } from "@/lib/change/filter";
import { byDay, canUndo, toHistoryRow } from "@/lib/change/row";
import type { ChangeRow } from "./fold";
import { changeRowId } from "./use-keyboard";

type WhoChoice = ChangeWho | "everyone";

export function ChangesList({
  rows,
  filters,
  counts,
  loops,
  canEdit,
  selected,
  open,
  now,
  hrefFor,
  onFilters,
  onSelect,
  onToggleFold,
  onUndo,
}: {
  rows: ChangeRow[];
  filters: ChangeFilters;
  counts: ChangeCounts | undefined;
  loops: { key: string; name: string }[];
  canEdit: boolean;
  selected: string | null;
  open: Set<string>;
  now: number;
  hrefFor: (changeId: string) => string;
  onFilters: (filters: ChangeFilters) => void;
  onSelect: (key: string) => void;
  onToggleFold: (id: string) => void;
  onUndo: (row: ChangeRow) => void;
}) {
  const count = whoCounts(counts);
  const loopOptions = [
    { value: "", label: "Any loop" },
    ...loops.map((loop) => ({ value: loop.key, label: loop.name })),
    ...(filters.loop && !loops.some((loop) => loop.key === filters.loop) ? [{ value: filters.loop, label: filters.loop }] : []),
  ];
  const kindOptions = [
    { value: "", label: "Any kind" },
    ...CHANGE_KINDS.map((kind) => ({ value: kind, label: kind })),
    ...(filters.kind && !CHANGE_KINDS.includes(filters.kind) ? [{ value: filters.kind, label: filters.kind }] : []),
  ];

  return (
    <List
      groups={byDay(rows, (row) => row.entry, now)}
      rowKey={(row) => row.key}
      canEdit={canEdit}
      controls={
        <>
          <Segmented<WhoChoice>
            label="Who"
            value={filters.who ?? "everyone"}
            options={[
              { value: "everyone", label: "Everyone", count: count.everyone },
              { value: "member", label: "People", count: count.member },
              { value: "connection", label: "Agents", count: count.connection },
              { value: "qbrix", label: "qbrix", count: count.qbrix },
            ]}
            onChange={(who) => onFilters({ ...filters, who: who === "everyone" ? null : who })}
          />
          <FilterChoice
            label="Loop"
            icon={Box}
            value={filters.loop}
            options={loopOptions}
            onChange={(loop) => onFilters({ ...filters, loop: loop || null })}
          />
          <FilterChoice
            label="Kind"
            icon={Tag}
            value={filters.kind}
            options={kindOptions}
            onChange={(kind) => onFilters({ ...filters, kind: kind || null })}
          />
          <FilterToggle
            label="Can undo"
            icon={Undo2}
            pressed={filters.undoable}
            onChange={(undoable) => onFilters({ ...filters, undoable })}
          />
          {filters.metric && (
            <FilterToggle label={filters.metric} icon={Target} pressed onChange={() => onFilters({ ...filters, metric: null })} />
          )}
          <span className="n-label ml-auto font-normal text-n-text-3">
            {canEdit ? "j k to move  ·  u to undo" : "j k to move"}
          </span>
        </>
      }
      empty={
        <div className="flex flex-col items-start gap-3">
          <p className="n-body text-n-text-2">{noneMatch(filters)}</p>
          <Button variant="secondary" size="sm" onClick={() => onFilters(NO_FILTERS)}>
            Clear filters
          </Button>
        </div>
      }
      renderRow={(row) => {
        const { entry, key, foldKey } = row;
        const expanded = open.has(entry.id);
        const data = toHistoryRow(entry, now);
        return (
          <div id={changeRowId(key)}>
            <Change
              layout="history"
              change={data.tag && entry.undone_by ? { ...data, tag: { ...data.tag, href: hrefFor(entry.undone_by.id) } } : data}
              canEdit={canEdit}
              selected={selected === key}
              onSelect={() => onSelect(key)}
              actions={canUndo(entry) ? { undo: () => onUndo(row) } : undefined}
              fold={
                entry.count > 1 && !foldKey
                  ? {
                      label: expanded ? "Hide" : `Show all ${entry.count}`,
                      expanded,
                      onToggle: () => onToggleFold(entry.id),
                    }
                  : undefined
              }
              className={foldKey ? "ml-8" : undefined}
            />
          </div>
        );
      }}
    />
  );
}

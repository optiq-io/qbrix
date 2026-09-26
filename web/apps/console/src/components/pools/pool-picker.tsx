"use client";

import { Lock, Plus, X } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { VariantChip } from "./variant-chip";
import { POOL_DRAFT_MESSAGE } from "@/lib/pools/use-pool-draft";
import type { usePoolDraft } from "@/lib/pools/use-pool-draft";
import type { Pool } from "@/lib/api/types";

// board `APP · New pool · ALT B — Inside new experiment`.
//
// a pool exists to be experimented on, so this is where most people need one.
// choosing an existing pool and writing a new one are the same decision, and
// they are presented as one list rather than a picker with an escape hatch.

type Draft = ReturnType<typeof usePoolDraft>;

export function PoolPicker({
  pools,
  value,
  onChange,
  drafting,
  onDraftingChange,
  draft,
  createdPool,
}: {
  pools: Pool[];
  value: string;
  onChange: (poolId: string) => void;
  drafting: boolean;
  onDraftingChange: (next: boolean) => void;
  draft: Draft;
  /** set once the draft has been created — the experiment submit failed after
      it, so the pool is real now and must not be created twice */
  createdPool: Pool | null;
}) {
  if (createdPool) {
    return (
      <div className="flex flex-col gap-2">
        <PoolRow pool={createdPool} selected onSelect={() => undefined} />
        <p className="text-[11.5px] leading-[1.5] text-text-faint">
          This pool was created. Only the experiment still needs to be saved.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {pools.map((pool) => (
        <PoolRow
          key={pool.id}
          pool={pool}
          selected={!drafting && value === pool.id}
          onSelect={() => {
            onDraftingChange(false);
            onChange(pool.id);
          }}
        />
      ))}

      {drafting ? (
        <PoolDraft draft={draft} onCancel={() => onDraftingChange(false)} />
      ) : (
        <button
          type="button"
          onClick={() => onDraftingChange(true)}
          className="flex items-center gap-[9px] rounded-[10px] border border-border-subtle px-3.5 py-3 text-left transition-colors hover:border-border"
        >
          <Plus size={14} className="shrink-0 text-text-dim" />
          <span className="text-[13.5px] font-medium text-text-dim">New pool</span>
        </button>
      )}
    </div>
  );
}

function PoolRow({
  pool,
  selected,
  onSelect,
}: {
  pool: Pool;
  selected: boolean;
  onSelect: () => void;
}) {
  const arms = pool.arms ?? [];
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "flex items-center gap-3 rounded-[10px] border px-3.5 py-3 text-left transition-colors",
        selected
          ? "border-accent-dim bg-accent-soft"
          : "border-border bg-bg-panel hover:border-border-strong",
      )}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span
          className={cn(
            "truncate text-[13.5px] font-medium",
            selected ? "text-accent" : "text-text-primary",
          )}
        >
          {pool.name}
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          {arms.map((arm) => (
            <VariantChip key={arm.id} name={arm.name} index={arm.index} size="sm" />
          ))}
        </span>
      </span>
      <span className="shrink-0 text-[12.5px] text-text-faint">
        {arms.length} {arms.length === 1 ? "variant" : "variants"}
      </span>
    </button>
  );
}

function PoolDraft({ draft, onCancel }: { draft: Draft; onCancel: () => void }) {
  return (
    <div className="flex flex-col gap-3 rounded-[10px] border border-accent-dim bg-accent-soft px-3.5 py-3.5">
      <div className="flex items-center gap-[10px]">
        <Plus size={14} className="shrink-0 text-accent" />
        <span className="text-[13.5px] font-medium text-accent">New pool</span>
        <span className="flex-1" />
        <span className="text-[12px] text-text-faint">
          created with the experiment
        </span>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Discard this pool"
          className="shrink-0 text-text-dim transition-colors hover:text-text-primary"
        >
          <X size={14} />
        </button>
      </div>

      <input
        value={draft.name}
        onChange={(e) => draft.setName(e.target.value)}
        placeholder="Pool name"
        autoFocus
        className="rounded-[9px] border border-border bg-bg-overlay px-3 py-[9px] text-[13.5px] text-text-primary outline-none transition-colors placeholder:text-text-faint focus:border-border-strong"
      />

      <div className="flex flex-wrap items-center gap-2">
        {draft.variants.map((variant, i) => (
          <span
            key={variant.id}
            className="flex items-center gap-2 rounded-[7px] border border-border bg-bg-overlay py-[5px] pl-2.5 pr-1.5"
          >
            <span className={cn("size-[6px] shrink-0 rounded-full", dotFor(i))} />
            <input
              value={variant.name}
              onChange={(e) => draft.updateVariant(variant.id, "name", e.target.value)}
              placeholder={`variant-${i + 1}`}
              size={Math.max(variant.name.length || 9, 9)}
              className="bg-transparent text-[12.5px] text-text-primary outline-none placeholder:text-text-faint"
            />
            <button
              type="button"
              onClick={() => draft.removeVariant(variant.id)}
              aria-label={`Remove ${variant.name || "variant"}`}
              disabled={draft.variants.length <= 1}
              className="shrink-0 text-text-faint transition-colors hover:text-text-primary disabled:opacity-30"
            >
              <X size={11} />
            </button>
          </span>
        ))}
        <button
          type="button"
          onClick={draft.addVariant}
          className="flex items-center gap-1.5 rounded-[7px] border border-border-subtle px-2.5 py-[6px] text-[12.5px] text-text-dim transition-colors hover:border-border hover:text-text-secondary"
        >
          <Plus size={11} />
          Variant
        </button>
      </div>

      <p className="flex items-start gap-2 text-[11.5px] leading-[1.5] text-text-dim">
        <Lock size={12} className="mt-[2px] shrink-0 text-amber" />
        {draft.issue && draft.issue !== "name"
          ? POOL_DRAFT_MESSAGE[draft.issue]
          : "Variants are fixed once the pool exists — everything the learner knows is indexed by them, so none can be added or removed later."}
      </p>
    </div>
  );
}

const DOTS = [
  "bg-viz-1",
  "bg-viz-2",
  "bg-viz-3",
  "bg-viz-4",
  "bg-viz-5",
  "bg-viz-6",
];
const dotFor = (i: number) => DOTS[i % DOTS.length];

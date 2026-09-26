"use client";

import { useState } from "react";
import { Lock, Plus, X } from "lucide-react";
import { DataRow, Cell } from "@qbrix/ui/components/data-table";
import { useToast } from "@qbrix/ui/components/toast";
import { cn } from "@qbrix/ui/lib/utils";
import { vizSeries } from "@qbrix/ui/components/belief-viz";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import {
  POOL_DRAFT_MESSAGE,
  usePoolDraft,
} from "@/lib/pools/use-pool-draft";

// board `APP · New pool · ALT A — Inline on Pools`.
//
// a pool is a name and a list of variants, which is exactly what the row next
// to it already shows. writing one in the table means the columns you fill are
// the columns you will read it back in, and nothing has to cover the list you
// were looking at to ask you for two fields.

export function PoolDraftRow({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => void;
}) {
  const draft = usePoolDraft();
  const toast = useToast();
  const toastApiError = useApiErrorToast();
  const [touched, setTouched] = useState(false);

  async function submit() {
    setTouched(true);
    if (!draft.ready) return;
    try {
      await draft.submit();
      toast.success("Pool created");
      onCreated();
    } catch (err) {
      toastApiError(err, "Failed to create the pool");
    }
  }

  const problem = touched && draft.issue ? POOL_DRAFT_MESSAGE[draft.issue] : null;

  return (
    <div className="border-y border-accent-dim bg-accent-soft">
      <DataRow height={64} className="hover:bg-transparent">
        <Cell width={260}>
          <input
            value={draft.name}
            onChange={(e) => draft.setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") onCancel();
            }}
            placeholder="Pool name"
            autoFocus
            aria-label="Pool name"
            className="w-full rounded-[9px] border border-accent-dim bg-bg-overlay px-3 py-2 text-[14px] font-medium text-text-primary outline-none placeholder:text-text-faint focus:border-accent/50"
          />
        </Cell>

        <Cell clip={false}>
          <div className="flex flex-wrap items-center gap-2">
            {draft.variants.map((variant, i) => (
              <span
                key={variant.id}
                className="flex items-center gap-2 rounded-[7px] border border-border bg-bg-overlay py-[5px] pl-2.5 pr-1.5"
              >
                <span
                  className={cn("size-[6px] shrink-0 rounded-full", vizSeries(i))}
                />
                <input
                  value={variant.name}
                  onChange={(e) =>
                    draft.updateVariant(variant.id, "name", e.target.value)
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submit();
                    if (e.key === "Escape") onCancel();
                  }}
                  placeholder={`variant-${i + 1}`}
                  aria-label={`Variant ${i + 1} name`}
                  size={Math.max(variant.name.length || 9, 9)}
                  className="bg-transparent text-[12.5px] text-text-primary outline-none placeholder:text-text-faint"
                />
                <button
                  type="button"
                  onClick={() => draft.removeVariant(variant.id)}
                  aria-label={`Remove ${variant.name || `variant ${i + 1}`}`}
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
        </Cell>

        <Cell width={130}>
          <span className="font-mono text-[13px] tracking-[0.3px] text-text-dim">
            {draft.variants.length}
          </span>
        </Cell>

        {/* the three trailing columns (112 · 112 · 64) collapse into one cell
            here, so it has to absorb the two 18px gaps they no longer create —
            without that the ARMS count sits 36px right of the rows below it */}
        <Cell width={112 + 112 + 64 + 18 * 2} clip={false}>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="flex h-[34px] shrink-0 items-center rounded-[9px] border border-border px-3.5 text-[13px] font-medium text-text-dim transition-colors hover:border-border-strong hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={draft.submitting}
              className="flex h-[34px] shrink-0 items-center rounded-[9px] bg-accent px-3.5 text-[13px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:pointer-events-none disabled:opacity-50"
            >
              {draft.submitting ? "Creating…" : "Create pool"}
            </button>
          </div>
        </Cell>
      </DataRow>

      <p className="flex items-start gap-2 px-7 pb-3 text-[12px] leading-[1.5] text-text-dim">
        <Lock size={12} className="mt-[3px] shrink-0 text-amber" />
        {problem ??
          "Variants are fixed once the pool exists — everything the learner knows is indexed by them, so none can be added or removed later."}
      </p>
    </div>
  );
}

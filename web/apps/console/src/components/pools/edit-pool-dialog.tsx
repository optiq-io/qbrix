"use client";

import { useState } from "react";
import { Dialog, DialogButton } from "@qbrix/ui/components/dialog";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { pools as poolsApi } from "@/lib/api/pools";
import { resolveApiError, type ResolvedApiError } from "@/lib/api/handle-error";
import type { Pool } from "@/lib/api/types";

// renaming is the whole of editing a pool: its variants are fixed at creation
// and there is no endpoint that could change them. the eyebrow says so, because
// "Edit pool" otherwise promises a form that does not exist.

export function EditPoolDialog({
  open,
  onClose,
  onSaved,
  pool,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (updated: Pool) => void;
  pool: Pool;
}) {
  const [name, setName] = useState(pool.name);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ResolvedApiError | null>(null);

  async function save() {
    const trimmed = name.trim();
    if (!trimmed) return;

    setError(null);
    setLoading(true);
    try {
      const updated = await poolsApi.update(pool.id, { name: trimmed });
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(resolveApiError(err, "Failed to rename the pool"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Rename pool"
      eyebrow={`${pool.arms.length} variants · fixed at creation`}
      width={480}
      dismissable={!loading}
      footer={
        <div className="flex w-full items-center justify-end gap-2.5">
          <DialogButton onClick={onClose} disabled={loading}>
            Cancel
          </DialogButton>
          <DialogButton
            variant="primary"
            onClick={save}
            disabled={loading || !name.trim()}
          >
            {loading ? "Saving…" : "Save"}
          </DialogButton>
        </div>
      }
    >
      <label className="flex flex-col gap-2">
        <span className="text-[13px] text-text-dim">Name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && name.trim() && !loading) save();
          }}
          autoFocus
          className="rounded-[9px] border border-border bg-bg-panel px-3 py-[9px] text-[13.5px] text-text-primary outline-none transition-colors placeholder:text-text-faint focus:border-border-strong"
        />
      </label>

      {error && (
        <InlineBanner tone="danger">
          <span className="flex flex-col gap-1">
            <span className="font-medium">{error.message}</span>
            {error.hint && (
              <span className="text-[11.5px] opacity-80">{error.hint}</span>
            )}
          </span>
        </InlineBanner>
      )}
    </Dialog>
  );
}

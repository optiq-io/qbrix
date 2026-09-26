"use client";

import { useState } from "react";
import { X } from "lucide-react";
import type { APIKey } from "@/lib/api/types";

// `PATCH /auth/api-keys/{id}` is name-only, and the name is the sole thing a
// row can be identified by — the key itself is a hash. mirrors
// `components/pools/edit-pool-dialog.tsx`.
export function RenameApiKeyDialog({
  apiKey,
  saving,
  onSave,
  onClose,
}: {
  apiKey: APIKey;
  saving: boolean;
  onSave: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(apiKey.name);
  const [error, setError] = useState("");

  function handleSave() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("name is required");
      return;
    }
    setError("");
    onSave(trimmed);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      <div className="relative z-10 flex w-[480px] flex-col overflow-hidden rounded-xl border border-border bg-bg-panel">
        <div className="flex flex-col gap-1 border-b border-border px-7 py-6">
          <div className="flex items-center justify-between">
            <h2 className="font-heading text-lg font-bold text-text-primary">
              Rename API key
            </h2>
            <button
              type="button"
              aria-label="Close"
              onClick={onClose}
              className="text-text-secondary transition-colors hover:text-text-primary"
            >
              <X size={20} />
            </button>
          </div>
          <p className="text-[13px] text-text-secondary">
            The key itself is unchanged and keeps working.
          </p>
        </div>

        <div className="flex flex-col gap-5 px-7 py-6">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="rename-api-key"
              className="text-[13px] font-medium text-text-secondary"
            >
              Key name
            </label>
            <input
              id="rename-api-key"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSave()}
              className="w-full rounded-lg border border-border bg-bg px-3.5 py-2.5 text-[13px] text-text-primary outline-none transition-colors placeholder:text-text-dim focus:border-text-dim"
              autoFocus
            />
          </div>

          {error && (
            <div className="rounded-lg border border-danger/20 bg-danger/10 px-4 py-3 text-[13px] text-danger">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-border px-7 py-5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border px-5 py-2.5 text-[13px] font-medium text-text-secondary transition-colors hover:border-text-dim hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-[13px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

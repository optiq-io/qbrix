"use client";

import { useEffect, useState } from "react";
import { X, Copy, Check } from "lucide-react";
import type { APIKeyCreateResponse } from "@/lib/api/types";

// the board does not draw this dialog, so it follows the console's current
// dialog convention (`components/pools/create-pool-dialog.tsx`).
//
// one dialog serves create and rotate: both endpoints answer with an
// `APIKeyCreateResponse` carrying the plain key, and that key exists in exactly
// that one response — the row stores a SHA-256 hash. so the panel below is the
// only place it will ever be readable.

export function ApiKeySecretDialog({
  open,
  secret,
  creating,
  onCreate,
  onClose,
}: {
  open: boolean;
  /** present once the key has been issued — by create *or* by rotate, in which
      case the dialog opens straight into the secret panel */
  secret: APIKeyCreateResponse | null;
  creating: boolean;
  onCreate: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) {
      setName("");
      setError("");
      setCopied(false);
    }
  }, [open]);

  if (!open) return null;

  function handleCreate() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("name is required");
      return;
    }
    setError("");
    onCreate(trimmed);
  }

  function handleCopy() {
    if (!secret) return;
    navigator.clipboard.writeText(secret.key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      <div className="relative z-10 flex w-[520px] flex-col overflow-hidden rounded-xl border border-border bg-bg-panel">
        <div className="flex flex-col gap-1 border-b border-border px-7 py-6">
          <div className="flex items-center justify-between">
            <h2 className="font-heading text-lg font-bold text-text-primary">
              {secret ? "Copy your API key" : "Create API key"}
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
            {secret
              ? "This is the only time it will be shown. Keys are stored as a SHA-256 hash and cannot be recovered."
              : "The key inherits your role's scopes. It is shown once at creation."}
          </p>
        </div>

        <div className="flex flex-col gap-5 px-7 py-6">
          {!secret ? (
            <>
              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="api-key-name"
                  className="text-[13px] font-medium text-text-secondary"
                >
                  Key name
                </label>
                <input
                  id="api-key-name"
                  type="text"
                  placeholder="e.g. production · web"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                  className="w-full rounded-lg border border-border bg-bg px-3.5 py-2.5 text-[13px] text-text-primary outline-none transition-colors placeholder:text-text-dim focus:border-text-dim"
                  autoFocus
                />
              </div>

              {error && (
                <div className="rounded-lg border border-danger/20 bg-danger/10 px-4 py-3 text-[13px] text-danger">
                  {error}
                </div>
              )}
            </>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-medium text-text-secondary">
                  {secret.name}
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={secret.key}
                    readOnly
                    onFocus={(e) => e.currentTarget.select()}
                    className="min-w-0 flex-1 rounded-lg border border-border bg-bg px-3.5 py-2.5 font-mono text-[13px] text-text-primary outline-none"
                  />
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="flex shrink-0 items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-[13px] font-medium text-text-secondary transition-colors hover:border-text-dim"
                  >
                    {copied ? (
                      <>
                        <Check size={14} className="text-positive" />
                        <span className="text-positive">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy size={14} />
                        <span>Copy</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              <div className="rounded-lg border border-accent-dim bg-accent-soft px-4 py-3 text-[13px] text-text-secondary">
                Store it somewhere safe now — closing this dialog is the last
                chance to read it.
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-border px-7 py-5">
          {!secret ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-border px-5 py-2.5 text-[13px] font-medium text-text-secondary transition-colors hover:border-text-dim hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating}
                className="flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-[13px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
              >
                {creating ? "Creating…" : "Create key"}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-accent px-5 py-2.5 text-[13px] font-semibold text-bg transition-colors hover:bg-accent/90"
            >
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

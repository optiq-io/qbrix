"use client";

import { useState } from "react";
import { X, Copy, Check, Loader2, Mail } from "lucide-react";
import { auth } from "@/lib/api/auth";

interface InviteDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function InviteDialog({ open, onClose, onCreated }: InviteDialogProps) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member" | "viewer">("member");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [inviteUrl, setInviteUrl] = useState("");
  const [copied, setCopied] = useState(false);

  function reset() {
    setEmail("");
    setRole("member");
    setError("");
    setInviteUrl("");
    setCopied(false);
    setLoading(false);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const invite = await auth.createInvite({ email, role });
      setInviteUrl(invite.invite_url ?? "");
      onCreated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "failed to create invite");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-[480px] rounded-xl border border-border bg-bg-panel p-6">
        {/* header */}
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-heading text-lg font-bold text-text-primary">
            Invite Member
          </h3>
          <button
            onClick={handleClose}
            className="text-text-dim hover:text-text-secondary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {inviteUrl ? (
          /* success state */
          <div className="flex flex-col gap-4">
            <p className="text-[13px] text-text-secondary">
              Invite created for <span className="font-semibold text-text-primary">{email}</span>. Share this link:
            </p>
            <div className="flex items-center gap-2 rounded-lg border border-border bg-bg p-3">
              <input
                type="text"
                readOnly
                value={inviteUrl}
                className="flex-1 bg-transparent font-mono text-xs text-text-secondary outline-none"
              />
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-semibold text-bg transition-colors hover:bg-accent/90"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="text-[11px] text-text-dim">
              This link expires in 72 hours.
            </p>
            <button
              onClick={handleClose}
              className="mt-2 rounded-lg border border-border px-4 py-2.5 text-[13px] font-medium text-text-secondary hover:border-text-dim transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          /* form */
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {error && (
              <div className="rounded-lg bg-danger/10 border border-danger/20 px-4 py-3 text-[13px] text-danger">
                {error}
              </div>
            )}

            <div className="flex flex-col gap-2">
              <label className="text-[13px] font-medium text-text-dim">
                Email Address
              </label>
              <div className="flex items-center gap-2.5 rounded-lg border border-border bg-bg px-3 py-2.5">
                <Mail size={16} className="text-text-dim" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="flex-1 bg-transparent text-[13px] text-text-primary placeholder:text-text-dim outline-none"
                />
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-[13px] font-medium text-text-dim">
                Role
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as "admin" | "member" | "viewer")}
                className="rounded-lg border border-border bg-bg px-3 py-2.5 text-[13px] text-text-primary outline-none"
              >
                <option value="member">Member</option>
                <option value="admin">Admin</option>
                <option value="viewer">Viewer</option>
              </select>
            </div>

            <div className="flex items-center justify-end gap-3 mt-2">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-lg border border-border px-4 py-2.5 text-[13px] font-medium text-text-secondary hover:border-text-dim transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={loading}
                className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-[13px] font-semibold text-bg hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                {loading && <Loader2 size={14} className="animate-spin" />}
                Send Invite
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

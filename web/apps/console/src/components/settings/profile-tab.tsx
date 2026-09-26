"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { useToast } from "@qbrix/ui/components/toast";
import { auth } from "@/lib/api/auth";
import { useAuth } from "@/lib/auth/context";
import { planLabel } from "@/lib/edition";
import {
  SettingsHead,
  FactStrip,
  Fact,
  FieldRow,
  Chip,
  fieldInput,
  btnPrimary,
  btnSecondary,
  btnDanger,
  formatDay,
} from "./chrome";

// board `APP · Settings / Profile`. head band, a mono fact strip, then one
// hairline row per thing you can actually change — no cards, per foundation
// rule 03.
//
// what the board does not draw, because nothing can fill it:
//   · an avatar upload — there is no avatar field on User and no upload route;
//     the initials block in the head is derived, not stored.
//   · an email change — `UpdateProfileRequest` is name-only, and the address
//     is the login identity. the row states that rather than offering a
//     control that would 422.

function initialsOf(name: string): string {
  return name
    .split(/[\s.]+/)
    .map((part) => part[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

export function ProfileTab() {
  const toast = useToast();
  const { user, updateUser } = useAuth();

  const [name, setName] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);

  const saveName = useMutation({
    mutationFn: (value: string) => auth.updateProfile({ name: value }),
    onSuccess: (updated) => {
      updateUser(updated);
      setName(null);
      toast.success("Profile updated");
    },
  });

  const changePassword = useMutation({
    mutationFn: () =>
      auth.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => {
      closePasswordForm();
      toast.success("Password updated");
    },
  });

  const deleteAccount = useMutation({
    mutationFn: () => auth.deleteAccount({ password: deletePassword }),
    onSuccess: () => {
      // a hard navigation, not router.push: the account is gone and every
      // provider above this one is holding state that no longer resolves
      window.location.href = "/login";
    },
  });

  if (!user) return null;

  const displayName = user.name || user.email.split("@")[0];
  const draftName = name ?? user.name ?? "";
  const nameDirty = draftName.trim() !== (user.name ?? "") && draftName.trim() !== "";

  function closePasswordForm() {
    setShowPassword(false);
    setCurrent("");
    setNext("");
    setConfirm("");
    setPasswordError("");
  }

  function submitPassword() {
    if (next.length < 8) {
      setPasswordError("New password must be at least 8 characters.");
      return;
    }
    if (next !== confirm) {
      setPasswordError("The two new passwords do not match.");
      return;
    }
    setPasswordError("");
    changePassword.mutate();
  }

  return (
    <div className="flex flex-1 flex-col">
      <SettingsHead
        title="Profile"
        description="Your account and how you sign in. Your name is what teammates see on invites and beside every change you make."
        meta={
          <div className="flex items-center gap-3">
            <div className="flex size-[38px] shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-[13.5px] font-semibold text-text-secondary">
              {initialsOf(displayName)}
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-[15px] font-medium text-text-primary">
                {displayName}
              </span>
              <span className="font-mono text-[12.5px] text-text-faint">
                {user.email}
              </span>
            </div>
          </div>
        }
      />

      <FactStrip>
        <Fact label="Role" value={user.role} />
        {user.plan_tier && (
          <Fact label="Plan" value={planLabel(user.plan_tier)} />
        )}
        <Fact label="Member since" value={formatDay(user.created_at)} />
        <Fact
          label="Account"
          value={user.is_active ? "Active" : "Deactivated"}
        />
      </FactStrip>

      <FieldRow
        label="Name"
        description="Shown to teammates on invites and beside every change you make."
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <input
            type="text"
            aria-label="Name"
            value={draftName}
            onChange={(e) => setName(e.target.value)}
            className={fieldInput}
          />
          <button
            type="button"
            onClick={() => saveName.mutate(draftName.trim())}
            disabled={!nameDirty || saveName.isPending}
            className={btnPrimary}
          >
            {saveName.isPending && <Loader2 size={14} className="animate-spin" />}
            Save
          </button>
        </div>
      </FieldRow>

      <FieldRow
        label="Email"
        description="The address you sign in with. Contact support to change it."
      >
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <span className="font-mono text-[14px] text-text-secondary">
            {user.email}
          </span>
          {user.email_verified ? (
            <Chip>verified</Chip>
          ) : (
            <Chip tone="amber">unverified</Chip>
          )}
        </div>
      </FieldRow>

      <FieldRow
        label="Password"
        description="At least 8 characters. Changing it does not sign your other sessions out."
      >
        {showPassword ? (
          <div className="flex flex-col items-start gap-2.5">
            <input
              type="password"
              autoComplete="current-password"
              placeholder="Current password"
              aria-label="Current password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className={fieldInput}
            />
            <input
              type="password"
              autoComplete="new-password"
              placeholder="New password"
              aria-label="New password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              className={fieldInput}
            />
            <input
              type="password"
              autoComplete="new-password"
              placeholder="Confirm new password"
              aria-label="Confirm new password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={fieldInput}
            />

            {passwordError && (
              <InlineBanner className="w-[320px] max-w-full">
                {passwordError}
              </InlineBanner>
            )}

            <div className="flex items-center gap-2.5 pt-0.5">
              <button
                type="button"
                onClick={submitPassword}
                disabled={
                  !current || !next || !confirm || changePassword.isPending
                }
                className={btnPrimary}
              >
                {changePassword.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Update password
              </button>
              <button
                type="button"
                onClick={closePasswordForm}
                className={btnSecondary}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowPassword(true)}
            className={btnSecondary}
          >
            Change password
          </button>
        )}
      </FieldRow>

      <FieldRow
        label="Delete account"
        tone="danger"
        description="Permanently removes your account and everything you own in it. This cannot be undone."
      >
        <input
          type="password"
          autoComplete="current-password"
          placeholder="Enter your password to confirm"
          aria-label="Password"
          value={deletePassword}
          onChange={(e) => setDeletePassword(e.target.value)}
          className={fieldInput}
        />
        <button
          type="button"
          onClick={() => setDeleteOpen(true)}
          disabled={!deletePassword || deleteAccount.isPending}
          className={btnDanger}
        >
          Delete account
        </button>
      </FieldRow>

      {/* was a bare window.confirm(), which is the one destructive path in the
          console that never got the shared dialog */}
      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => deleteAccount.mutate()}
        title="Delete account"
        message="Your account and everything you own in this workspace is removed immediately. This cannot be undone."
        confirmLabel="Delete account"
        loadingLabel="Deleting…"
        loading={deleteAccount.isPending}
      />
    </div>
  );
}

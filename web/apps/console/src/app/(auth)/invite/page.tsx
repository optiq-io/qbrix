"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { Lock, User, Loader2, TriangleAlert, UserPlus } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { MonoLabel } from "@qbrix/ui/components/mono-label";
import { auth } from "@/lib/api/auth";
import { resolveApiError } from "@/lib/api/handle-error";
import { AuthShell } from "@/components/auth/auth-shell";
import { Field, fieldInput } from "@/components/auth/field";
import { TransactionalCard } from "@/components/auth/transactional-card";
import type { InviteValidationResponse } from "@/lib/api/types";

function InviteContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [invite, setInvite] = useState<InviteValidationResponse | null>(null);
  const [validating, setValidating] = useState(true);
  const [invalid, setInvalid] = useState(false);

  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      setInvalid(true);
      setValidating(false);
      return;
    }

    auth
      .validateInvite(token)
      .then(setInvite)
      .catch(() => setInvalid(true))
      .finally(() => setValidating(false));
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;

    setError("");
    setLoading(true);

    try {
      await auth.acceptInvite(token, { name, password });
      router.replace("/login?invited=true");
    } catch (err: unknown) {
      setError(resolveApiError(err, "failed to accept invite").message);
    } finally {
      setLoading(false);
    }
  }

  if (validating) {
    return (
      <div className="flex flex-col items-center gap-3 py-4">
        <Loader2 size={20} className="animate-spin text-text-dim" />
        <MonoLabel tone="dim">validating invite…</MonoLabel>
      </div>
    );
  }

  if (invalid || !invite) {
    return (
      <TransactionalCard
        icon={TriangleAlert}
        tone="danger"
        title="This invite isn't valid"
        body="The link is expired, already used, or was revoked. Ask whoever invited you to send a new one."
      >
        <Link href="/login" className="w-full">
          <Button variant="secondary" className="h-12 w-full text-[15.5px]">
            Back to sign in
          </Button>
        </Link>
      </TransactionalCard>
    );
  }

  // board `APP · Transactional states` / INVITE. two departures from it, both
  // forced by the api: the validate payload carries no inviter name, so the
  // body cannot say who invited you; and there is no decline endpoint, so the
  // second action is a way out rather than a state change. accepting also
  // creates the account, which is why the card carries a form the board omits.
  return (
    <TransactionalCard
      icon={UserPlus}
      title={`Join ${invite.workspace_name} on qbrix`}
      body="You've been invited to this workspace. Set a name and password to accept."
      meta={
        <MonoLabel tone="faint">{`Role · ${invite.role}`}</MonoLabel>
      }
    >
      {error && (
        <InlineBanner tone="danger" size="sm">
          {error}
        </InlineBanner>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-[18px] text-left">
        <Field label="Email" icon={User}>
          <span className="flex-1 truncate text-[15.5px] text-text-dim">
            {invite.email}
          </span>
        </Field>

        <Field label="Full name" icon={User}>
          <input
            type="text"
            required
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="your full name"
            className={fieldInput}
          />
        </Field>

        <Field label="Password" icon={Lock}>
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="min 8 characters"
            className={fieldInput}
          />
        </Field>

        <Button
          type="submit"
          disabled={loading}
          className="h-12 w-full text-[15.5px]"
        >
          {loading && <Loader2 size={15} className="animate-spin" />}
          Accept invite
        </Button>
      </form>

      <Link href="/login" className="w-full">
        <Button variant="secondary" className="h-12 w-full text-[15.5px]">
          Not now
        </Button>
      </Link>
    </TransactionalCard>
  );
}

export default function InvitePage() {
  return (
    <AuthShell>
      <Suspense>
        <InviteContent />
      </Suspense>
    </AuthShell>
  );
}

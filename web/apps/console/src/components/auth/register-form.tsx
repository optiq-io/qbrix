"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Mail,
  Lock,
  EyeOff,
  Eye,
  User,
  Loader2,
  Building2,
  Hash,
} from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { useAuth } from "@/lib/auth/context";
import { useDeployment } from "@/lib/deployment";
import { auth } from "@/lib/api/auth";
import { resolveApiError } from "@/lib/api/handle-error";
import { Field, fieldInput } from "./field";
import { useRetryAfter } from "./use-retry-after";
import { RegisterSentCard } from "./register-sent-card";
import { TransactionalCard } from "./transactional-card";

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .slice(0, 64);
}

export function RegisterForm() {
  const router = useRouter();
  const { register } = useAuth();
  const { isCloud, signupOpen, isLoading: loadingConfig } = useDeployment();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceSlug, setWorkspaceSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [registered, setRegistered] = useState(false);

  const limit = useRetryAfter();

  function handleWorkspaceNameChange(value: string) {
    setWorkspaceName(value);
    if (!slugTouched) {
      setWorkspaceSlug(toSlug(value));
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const user = await register(
        name,
        email,
        password,
        workspaceName || undefined,
        workspaceSlug || undefined,
      );
      // dev/invite flows return already-verified users who can sign in now;
      // otherwise the user must confirm their email first.
      if (user.email_verified) {
        router.replace("/login?registered=true");
      } else {
        setRegistered(true);
      }
    } catch (err: unknown) {
      if (limit.capture(err)) return;
      setError(resolveApiError(err, "registration failed").message);
    } finally {
      setLoading(false);
    }
  }

  if (registered) {
    return <RegisterSentCard email={email} onResend={auth.resendVerification} />;
  }

  if (!loadingConfig && !signupOpen) {
    return (
      <TransactionalCard
        icon={Lock}
        tone="neutral"
        title="Registration is closed"
        body="This qbrix instance does not accept public sign-ups. Ask an administrator to invite you."
      >
        <Link
          href="/login"
          className="text-[13.5px] font-medium text-text-primary transition-opacity hover:opacity-70"
        >
          Back to sign in
        </Link>
      </TransactionalCard>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col">
      <h1 className="text-[36px] font-medium leading-[1.1] tracking-[-0.039em] text-text-primary">
        Create account
      </h1>
      <p className="mt-2.5 text-[16px] leading-[1.5] text-text-dim">
        Get started with qbrix. No card required.
      </p>

      {(limit.blocked || error) && (
        <div className="mt-8 flex flex-col gap-4">
          {limit.blocked && (
            <InlineBanner tone="danger" size="sm">
              Too many attempts — try again in {limit.remaining}s.
            </InlineBanner>
          )}
          {error && !limit.blocked && (
            <InlineBanner tone="danger" size="sm">
              {error}
            </InlineBanner>
          )}
        </div>
      )}

      <div className="mt-8 flex flex-col gap-[18px]">
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

        <Field label="Organization" icon={Building2}>
          <input
            type="text"
            required
            autoComplete="organization"
            value={workspaceName}
            onChange={(e) => handleWorkspaceNameChange(e.target.value)}
            placeholder="Acme Inc."
            className={fieldInput}
          />
        </Field>

        <Field label="Workspace URL" icon={Hash}>
          <input
            type="text"
            required
            value={workspaceSlug}
            onChange={(e) => {
              setSlugTouched(true);
              setWorkspaceSlug(toSlug(e.target.value));
            }}
            placeholder="acme-inc"
            className={fieldInput}
          />
          {isCloud && (
            <span className="shrink-0 text-[15.5px] text-text-faint">
              .qbrix.io
            </span>
          )}
        </Field>

        <Field label="Email" icon={Mail}>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            className={fieldInput}
          />
        </Field>

        <Field label="Password" icon={Lock}>
          <input
            type={showPassword ? "text" : "password"}
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="min 8 characters"
            className={fieldInput}
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            className="text-text-faint transition-colors hover:text-text-secondary"
          >
            {showPassword ? <Eye size={15} /> : <EyeOff size={15} />}
          </button>
        </Field>
      </div>

      <Button
        type="submit"
        disabled={loading || limit.blocked}
        className="mt-6 h-[50px] w-full text-[15.5px]"
      >
        {loading && <Loader2 size={15} className="animate-spin" />}
        Create account
      </Button>

      {isCloud && (
        <p className="mt-4 text-[12.5px] leading-[1.6] text-text-faint">
          By creating an account you agree to the{" "}
          <a
            href="https://qbrix.io/terms"
            className="text-text-dim underline underline-offset-2 hover:text-text-secondary"
          >
            Terms
          </a>{" "}
          and{" "}
          <a
            href="https://qbrix.io/privacy"
            className="text-text-dim underline underline-offset-2 hover:text-text-secondary"
          >
            Privacy Policy
          </a>
          .
        </p>
      )}

      <div className="mt-6 flex items-center gap-1.5">
        <span className="text-[13.5px] text-text-dim">
          Already have an account?
        </span>
        <Link
          href="/login"
          className="text-[13.5px] font-medium text-text-primary transition-opacity hover:opacity-70"
        >
          Sign in
        </Link>
      </div>
    </form>
  );
}

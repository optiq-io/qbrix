"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Mail, Lock, EyeOff, Eye, KeyRound, Loader2 } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { useAuth } from "@/lib/auth/context";
import { auth } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/types";
import { resolveApiError } from "@/lib/api/handle-error";
import { takeCheckoutRedirect } from "@/lib/edition";
import { Field, fieldInput, authLabel } from "./field";
import { useRetryAfter } from "./use-retry-after";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, loginWithApiKey } = useAuth();

  const [mode, setMode] = useState<"credentials" | "apikey">("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // distinct handling for the email-not-verified case + its resend affordance
  const [unverified, setUnverified] = useState(false);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  const limit = useRetryAfter();

  const redirect = searchParams.get("redirect") ?? "/";
  const registered = searchParams.get("registered");
  const invited = searchParams.get("invited");
  const verified = searchParams.get("verified");
  const notice = registered || invited || verified;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setUnverified(false);
    setResent(false);
    setLoading(true);

    try {
      if (mode === "apikey") {
        await loginWithApiKey(apiKey);
      } else {
        await login(email, password);
      }
      const checkout = takeCheckoutRedirect();
      router.replace(checkout ?? redirect);
    } catch (err: unknown) {
      if (limit.capture(err)) return;
      if (err instanceof ApiError && err.code === "EMAIL_NOT_VERIFIED") {
        setUnverified(true);
        return;
      }
      setError(resolveApiError(err, "login failed").message);
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    setResending(true);
    try {
      await auth.resendVerification(email);
    } catch (err) {
      // enumeration-safe: always confirm, but a rate limit still has to show
      limit.capture(err);
    } finally {
      setResending(false);
      setResent(true);
    }
  }

  const busy = loading || limit.blocked;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col">
      <h1 className="text-[36px] font-medium leading-[1.1] tracking-[-0.039em] text-text-primary">
        Sign in
      </h1>
      <p className="mt-2.5 text-[16px] leading-[1.5] text-text-dim">
        Welcome back. Your experiments are still running.
      </p>

      <div className="mt-8 flex flex-col gap-4">
        {limit.blocked && (
          <InlineBanner tone="danger" size="sm">
            Too many attempts — try again in {limit.remaining}s.
          </InlineBanner>
        )}

        {notice && !error && !unverified && !limit.blocked && (
          <InlineBanner tone="positive" size="sm">
            {verified
              ? "Email verified — sign in to continue"
              : invited
                ? "Invite accepted — sign in to your new workspace"
                : "Account created — sign in to continue"}
          </InlineBanner>
        )}

        {unverified && (
          <InlineBanner tone="danger" size="sm">
            <div className="flex flex-col items-start gap-2.5">
              <span>
                your email isn&apos;t verified yet. check your inbox for the
                verification link to activate your account.
              </span>
              {resent ? (
                <span className="text-positive">
                  verification link sent — check your inbox.
                </span>
              ) : (
                <button
                  type="button"
                  onClick={handleResend}
                  disabled={resending}
                  className="flex items-center gap-2 rounded border border-border-strong px-3 py-1.5 text-text-secondary transition-colors hover:text-text-primary disabled:opacity-50"
                >
                  {resending && <Loader2 size={12} className="animate-spin" />}
                  Resend verification email
                </button>
              )}
            </div>
          </InlineBanner>
        )}

        {error && (
          <InlineBanner tone="danger" size="sm">
            {error}
          </InlineBanner>
        )}
      </div>

      {mode === "credentials" ? (
        <>
          <div className="mt-6 flex flex-col gap-[18px]">
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

            <Field
              label="Password"
              icon={Lock}
              trailing={
                <Link
                  href="/forgot-password"
                  className="text-[12px] text-text-dim transition-colors hover:text-text-secondary"
                >
                  Forgot?
                </Link>
              }
            >
              <input
                type={showPassword ? "text" : "password"}
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="your password"
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
            disabled={busy}
            className="mt-5 h-[50px] w-full text-[15.5px]"
          >
            {loading && <Loader2 size={15} className="animate-spin" />}
            {limit.blocked ? `Sign in (${limit.remaining})` : "Sign in"}
          </Button>

          <div className="mt-5 flex items-center gap-3.5">
            <span className="h-px flex-1 bg-border-subtle" />
            <span className={authLabel}>or</span>
            <span className="h-px flex-1 bg-border-subtle" />
          </div>

          {/* the board draws an SSO button here; sso is a plan-tier flag with
              no implementation, so the slot goes to the sign-in method that
              does exist and that the board never drew */}
          <Button
            variant="secondary"
            onClick={() => setMode("apikey")}
            className="mt-5 h-12 w-full text-[15.5px]"
          >
            <KeyRound size={15} />
            Sign in with API key
          </Button>
        </>
      ) : (
        <>
          <div className="mt-6">
            <Field label="API key" icon={KeyRound}>
              <input
                type="password"
                required
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="optiq_..."
                className={fieldInput}
              />
            </Field>
          </div>

          <Button
            type="submit"
            disabled={busy}
            className="mt-5 h-[50px] w-full text-[15.5px]"
          >
            {loading && <Loader2 size={15} className="animate-spin" />}
            Authenticate
          </Button>

          <Button
            variant="secondary"
            onClick={() => setMode("credentials")}
            className="mt-3 h-12 w-full text-[15.5px]"
          >
            <Mail size={15} />
            Use email instead
          </Button>
        </>
      )}

      <div className="mt-7 flex items-center gap-1.5">
        <span className="text-[13.5px] text-text-dim">No account yet?</span>
        <Link
          href="/register"
          className="text-[13.5px] font-medium text-text-primary transition-opacity hover:opacity-70"
        >
          Create one
        </Link>
      </div>
    </form>
  );
}

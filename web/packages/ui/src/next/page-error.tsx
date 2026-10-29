"use client";

import Link from "next/link";
import { ArrowRight, Check, Copy, RotateCw } from "lucide-react";
import { Button, buttonClass } from "./button";
import { useCopy } from "./copy";

type Home = { href: string; label: string };

function ErrorPage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col px-4 pt-16 pb-12 lg:pt-[120px] lg:pr-12 lg:pl-40">
      <div className="flex w-full max-w-[560px] flex-col">{children}</div>
    </div>
  );
}

export interface NotFoundProps {
  /** the path that didn't open, as the person followed it */
  path: string;
  /** what the link pointed to, such as "loop"; omit for an address that names nothing */
  noun?: string;
  workspace: string;
  email: string;
  /** the one key in this workspace within two edits of the link's, if exactly one is */
  closest?: { name: string; key: string; href: string };
  home: Home;
  onSwitchAccount: () => void;
}

/** every link that can't open: a key that never existed, a deleted draft, another
    workspace's object. it never says which */
export function NotFound({ path, noun, workspace, email, closest, home, onSwitchAccount }: NotFoundProps) {
  const reason = noun
    ? `The key may be mistyped, or the ${noun} isn't in this workspace.`
    : "The address may be mistyped, or what it pointed to isn't in this workspace.";

  return (
    <ErrorPage>
      <p className="n-label font-n-mono font-normal text-n-text-3">
        {noun ? `No ${noun} at` : "Nothing at"} {path}
      </p>
      <h1 className="n-lead mt-4 font-medium">
        There&apos;s {noun ? `no ${noun}` : "nothing"} at this link in {workspace}.
      </h1>
      <p className="n-support mt-4 text-n-text-2">
        {reason} You&apos;re signed in to {workspace} as {email}.
      </p>
      {closest && (
        <Link
          href={closest.href}
          className="n-body mt-6 flex items-center gap-2 rounded-n-panel bg-n-fill-1 p-3 transition-colors hover:bg-n-fill-2"
        >
          <span className="text-n-text-3">Closest in {workspace}:</span>
          <span className="font-medium text-n-text-1">{closest.name}</span>
          <span className="n-mono min-w-0 flex-1 truncate text-n-text-3">{closest.key}</span>
          <ArrowRight size={13} className="shrink-0 text-n-text-3" />
        </Link>
      )}
      <div className="mt-6 flex gap-2">
        <Link href={home.href} className={buttonClass("primary")}>
          {home.label}
        </Link>
        <Button variant="secondary" onClick={onSwitchAccount}>
          Switch account
        </Button>
      </div>
    </ErrorPage>
  );
}

export interface CouldntLoadProps {
  /** the failed response's X-Request-ID, for an admin to look up */
  requestId?: string;
  onRetry: () => void;
  home: Home;
}

/** a page whose request failed on the server */
export function CouldntLoad({ requestId, onRetry, home }: CouldntLoadProps) {
  const [copied, copy] = useCopy();
  const CopyIcon = copied ? Check : Copy;

  return (
    <ErrorPage>
      <h1 className="n-lead flex flex-col gap-2">
        <span className="font-medium">This page didn&apos;t load.</span>
        <span className="text-n-text-2">Nothing you did caused it.</span>
      </h1>
      <p className="n-support mt-4 text-n-text-2">
        Something went wrong on the server. Trying again usually fixes it.
        {requestId && " If it doesn't, send this request ID to an admin:"}
      </p>
      {requestId && (
        <button
          type="button"
          onClick={() => copy(requestId)}
          aria-label={copied ? "Copied" : "Copy request ID"}
          className="n-meta mt-4 flex items-center gap-2 self-start rounded-n-panel bg-n-fill-1 px-3 py-2 transition-colors hover:bg-n-fill-2"
        >
          <span className="text-n-text-3">request</span>
          <span className="n-mono text-n-text-1">{requestId}</span>
          <CopyIcon size={12} className="text-n-text-3" />
        </button>
      )}
      <div className="mt-6 flex gap-2">
        <Button onClick={onRetry}>
          <RotateCw size={14} />
          Try again
        </Button>
        <Link href={home.href} className={buttonClass("secondary")}>
          {home.label}
        </Link>
      </div>
    </ErrorPage>
  );
}

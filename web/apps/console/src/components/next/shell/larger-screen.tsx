"use client";

import { useState } from "react";
import Link from "next/link";
import { buttonClass } from "@qbrix/ui/next/button";
import { routes } from "@/config/routes";

export function LargerScreen() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col justify-center gap-3 px-4 lg:hidden">
      <Link href={routes.next.inbox} className="n-meta text-n-text-2">
        Inbox
      </Link>
      <h1 className="n-lead">This page opens on a larger screen</h1>
      <p className="n-support text-n-text-2">
        On a phone, qbrix opens your inbox and the changes waiting on you. Everything else opens
        at a desk; this link works on any computer you&apos;re signed in on.
      </p>
      <button type="button" onClick={copy} className={buttonClass("secondary", "lg", "mt-2")}>
        {copied ? "Link copied" : "Copy link"}
      </button>
    </div>
  );
}

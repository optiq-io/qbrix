"use client";

import { Check, Link as LinkIcon, Monitor } from "lucide-react";
import { buttonClass } from "./button";
import { useCopy } from "./copy";

/** on a phone, everything but the inbox and a change asks for a desk, and offers its own link */
export function LargerScreen({ title }: { title: string }) {
  const [copied, copy] = useCopy();
  const Icon = copied ? Check : LinkIcon;

  return (
    <section className="flex flex-col gap-3 rounded-n-panel border border-n-line-2 bg-n-bg p-4">
      <h2 className="flex items-center gap-2 text-[14px] font-medium leading-[1.3] text-n-text-1">
        <Monitor size={16} className="shrink-0 text-n-text-2" />
        {title}
      </h2>
      <p className="n-body text-n-text-2">
        On a phone, qbrix opens your inbox and the changes waiting on you. Everything else opens at a desk; this link
        works on any computer you&apos;re signed in on.
      </p>
      <button
        type="button"
        onClick={() => copy(window.location.href)}
        className={buttonClass("secondary", "lg", "w-full")}
      >
        <Icon size={16} />
        {copied ? "Link copied" : "Copy link"}
      </button>
    </section>
  );
}

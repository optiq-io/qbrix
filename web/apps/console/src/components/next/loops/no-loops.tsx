"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { buttonClass } from "@qbrix/ui/next/button";
import { Empty } from "@qbrix/ui/next/empty";
import { docsUrl, routes } from "@/config/routes";

const START_LOOP = "Start a loop for the checkout headline";

function mcpCommand(): string {
  const origin = new URL(process.env.NEXT_PUBLIC_API_URL || "/", window.location.origin).origin;
  return `claude mcp add qbrix ${origin}/mcp`;
}

export function NewLoopLink() {
  return (
    <Link href={routes.next.newLoop} className={buttonClass("primary", "sm")}>
      <Plus size={13} />
      New loop
    </Link>
  );
}

export function NoLoops({ canEdit }: { canEdit: boolean }) {
  return (
    <Empty
      agent={{
        title: "Let your agent draft it",
        line: "It finds the place in your code and drafts the loop. Nothing changes for your users until it launches.",
        prompt: START_LOOP,
        connect: { command: mcpCommand(), href: docsUrl("mcp-server") },
      }}
      hand={{
        title: "Make a loop yourself",
        line: "Name it, list its options and choose the metric it learns from. It starts as a draft, so nothing changes for your users until you launch it.",
        children: canEdit ? (
          <div>
            <NewLoopLink />
          </div>
        ) : null,
      }}
    />
  );
}

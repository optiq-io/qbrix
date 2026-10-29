"use client";

import { ArrowRight, Check, Copy } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";
import { useCopy } from "./copy";

/** a prompt to give an agent; the whole row copies it */
export function AgentPrompt({ prompt }: { prompt: string }) {
  const [copied, copy] = useCopy();
  const Icon = copied ? Check : Copy;

  return (
    <button
      type="button"
      onClick={() => copy(prompt)}
      aria-label={copied ? "Copied" : `Copy "${prompt}"`}
      className="flex w-full items-center gap-2 rounded-n-control border border-n-line p-2 text-left transition-colors hover:bg-n-fill-1"
    >
      <span className="n-meta min-w-0 flex-1 text-n-text-2">{prompt}</span>
      <Icon size={12} className="shrink-0 text-n-text-3" />
    </button>
  );
}

export function AskYourAgent({
  label = "Ask your agent",
  prompts,
  className,
}: {
  label?: string;
  prompts: string[];
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <span className="n-meta font-medium text-n-text-3">{label}</span>
      {prompts.map((prompt) => (
        <AgentPrompt key={prompt} prompt={prompt} />
      ))}
    </div>
  );
}

/** a call to copy into code: select, track, the line that adds qbrix to a client */
export function Code({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <pre
      className={cn(
        "n-label overflow-x-auto rounded-n-panel bg-n-fill-1 px-3 py-2 font-n-mono font-normal text-n-text-2",
        className,
      )}
    >
      {children}
    </pre>
  );
}

/** a lasting hint inside an empty or quiet page */
export function Note({
  icon: Icon,
  title,
  children,
  className,
}: {
  icon: LucideIcon;
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("n-meta flex gap-2 rounded-n-panel bg-n-fill-1 p-3", className)}>
      <Icon size={14} className="mt-0.5 shrink-0 text-n-text-3" />
      <div className="flex min-w-0 flex-col gap-0.5">
        {title && <span className="font-medium text-n-text-1">{title}</span>}
        <span className={title ? "text-n-text-3" : "text-n-text-2"}>{children}</span>
      </div>
    </div>
  );
}

type Way = { title: string; line: string };

export interface EmptyProps {
  /** the agent's way in; its prompt is required, so a form never shows without one */
  agent: Way & {
    prompt: string;
    /** shown for a person whose client isn't connected yet */
    connect?: { command: string; href: string };
  };
  /** the way by hand: the action or form that does the same thing */
  hand: Way & { children: React.ReactNode };
  className?: string;
}

/** both ways to start, side by side: ask your agent, or do it by hand */
export function Empty({ agent, hand, className }: EmptyProps) {
  return (
    <div className={cn("grid gap-6 md:grid-cols-2", className)}>
      <Card eyebrow="Ask your agent" title={agent.title} line={agent.line}>
        <AgentPrompt prompt={agent.prompt} />
        {agent.connect && (
          <>
            <p className="n-meta text-n-text-3">Not connected yet? Add qbrix to your client with one line:</p>
            <Code>{agent.connect.command}</Code>
            <a href={agent.connect.href} className="n-meta flex items-center gap-1 self-start text-n-text-2 hover:text-n-text-1">
              Cursor, VS Code and other clients
              <ArrowRight size={12} className="text-n-text-3" />
            </a>
          </>
        )}
      </Card>
      <Card eyebrow="By hand" title={hand.title} line={hand.line}>
        <span className="flex-1" />
        {hand.children}
      </Card>
    </div>
  );
}

function Card({ eyebrow, title, line, children }: Way & { eyebrow: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-n-panel border border-n-line bg-n-surface p-5">
      <span className="n-meta font-medium text-n-text-3">{eyebrow}</span>
      <h2 className="text-[15px] font-medium leading-[1.3] text-n-text-1">{title}</h2>
      <p className="n-body text-n-text-2">{line}</p>
      {children}
    </section>
  );
}

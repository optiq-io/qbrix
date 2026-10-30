import type { ChangeDiff } from "@qbrix/ui/next/change";
import type { Actor } from "@qbrix/ui/next/entity";

export type Token =
  | { kind: "text"; text: string }
  | { kind: "actor"; actor: Actor }
  | { kind: "loop"; name: string; href?: string }
  | { kind: "metric"; name: string; href?: string }
  | { kind: "option"; name: string; rank?: number };

export type HeaderEvent = {
  id: string;
  kind: string;
  /** when it happened, or when the last of a fold did, in ms */
  at: number;
  /** when the first of a fold happened */
  firstAt?: number;
  /** the sentence, rendered in order; spacing is the text tokens' own */
  pieces: Token[];
  diff?: ChangeDiff[];
  reason?: string;
  /** who or what it came from: "qbrix", "Sam", "#488" */
  source: string;
  /** what the time doesn't say: "decision errors" */
  context?: string;
  /** an unresolved alert: something qbrix noticed that still stands */
  alert?: boolean;
};

"use client";

import { useEffect, useRef } from "react";
import { format } from "date-fns";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Undo2 } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { Button } from "@qbrix/ui/next/button";
import { AskYourAgent } from "@qbrix/ui/next/empty";
import { actorName } from "@qbrix/ui/next/entity";
import { TextField } from "@qbrix/ui/next/field";
import { RailSection } from "@qbrix/ui/next/object-page";
import { changes } from "@/lib/api/changes";
import { queryKeys } from "@/lib/api/query-keys";
import type { ChangeEntry } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/context";
import { asSentence, type Refusal } from "@/lib/change/refusal";
import { canUndo, panelTime, undoConsequence, undoLabel } from "@/lib/change/row";
import { actorOf, sentence } from "@/lib/loop/event";

function askAbout(entry: ChangeEntry) {
  return `What did ${actorName(actorOf(entry))} change this week, and why?`;
}

function WhoRow({ label, mono, children }: { label: string; mono?: boolean; children: React.ReactNode }) {
  return (
    <div className="n-body grid grid-cols-[84px_minmax(0,1fr)] gap-2">
      <dt className="text-n-text-3">{label}</dt>
      <dd className={cn("min-w-0 break-words text-n-text-1", mono && "font-n-mono")}>{children}</dd>
    </div>
  );
}

function Who({ entry }: { entry: ChangeEntry }) {
  const { user } = useAuth();
  const actor = actorOf(entry);
  return (
    <RailSection title="Who">
      <dl className="flex flex-col gap-2">
        <WhoRow label="By">{actorName(actor)}</WhoRow>
        {actor.kind === "connection" && <WhoRow label="For">{actor.onBehalfOf}</WhoRow>}
        {actor.kind === "connection" && (
          <WhoRow label="Through">
            {actor.name} connection{user?.name === actor.onBehalfOf && " · acts as you"}
          </WhoRow>
        )}
        {actor.kind === "member" && <WhoRow label="Through">{actor.via ?? "the console"}</WhoRow>}
        {entry.request_id && (
          <WhoRow label="Request" mono>
            {entry.request_id}
          </WhoRow>
        )}
      </dl>
    </RailSection>
  );
}

function WhatChanged({ entry }: { entry: ChangeEntry }) {
  const lines = entry.diff.flatMap(({ field, before, after }) => [
    ...(before !== null ? [{ sign: "−", field, value: before }] : []),
    ...(after !== null ? [{ sign: "+", field, value: after }] : []),
  ]);
  if (lines.length === 0) return null;
  return (
    <RailSection title="What changed">
      <ul className="n-meta divide-y divide-n-line-2 rounded-n-panel border border-n-line font-n-mono">
        {lines.map(({ sign, field, value }, at) => (
          <li key={at} className="grid grid-cols-[12px_64px_minmax(0,1fr)] gap-2 px-3 py-2">
            <span aria-hidden className={sign === "+" ? "text-n-ok-fg" : "text-n-no-fg"}>
              {sign}
            </span>
            <span className="truncate text-n-text-3">{field}</span>
            <span className="min-w-0 break-words text-n-text-1">
              <span className="sr-only">{sign === "+" ? "after: " : "before: "}</span>
              {value}
            </span>
          </li>
        ))}
      </ul>
    </RailSection>
  );
}

function Moved({ laterId, onOpen }: { laterId: string; onOpen: (id: string) => void }) {
  const later = useQuery({
    queryKey: queryKeys.changes.detail(laterId),
    queryFn: () => changes.get(laterId),
  });
  const entry = later.data;
  const at = entry?.at ? ` at ${format(Date.parse(entry.at), "HH:mm")}` : "";
  const who = entry ? `${actorName(actorOf(entry))}'s change` : "the later change";

  return (
    <div className="flex flex-col gap-3">
      <div role="alert" className="flex flex-col gap-1 rounded-n-panel bg-n-part-bg p-3">
        <p className="n-body font-medium text-n-part-fg">Can&apos;t undo this one yet.</p>
        <p className="n-meta text-n-text-1">
          {entry && `${sentence(entry).replace(/\.$/, "")}${at}. `}
          Undo restores only what nothing has moved since; undo that change first.
        </p>
      </div>
      <div>
        <Button variant="secondary" onClick={() => onOpen(laterId)}>
          <ArrowRight size={13} className="text-n-text-2" />
          Open {who}
        </Button>
      </div>
    </div>
  );
}

function UndoSection({
  entry,
  refusal,
  reason,
  pending,
  foldOpen,
  confirming,
  onReason,
  onUndo,
  onDismiss,
  onOpen,
  onExpand,
}: {
  entry: ChangeEntry;
  refusal: Refusal | null;
  reason: string;
  pending: boolean;
  foldOpen: boolean;
  confirming: { id: string } | null;
  onReason: (reason: string) => void;
  onUndo: () => void;
  onDismiss: () => void;
  onOpen: (id: string) => void;
  onExpand: () => void;
}) {
  const reasonField = useRef<HTMLInputElement>(null);
  const consequence = undoConsequence(entry);

  useEffect(() => {
    if (confirming?.id === entry.id) reasonField.current?.focus();
  }, [confirming, entry.id]);

  if (entry.undone_by) {
    const { id, who } = entry.undone_by;
    return (
      <RailSection title="Undo">
        <p className="n-body text-n-text-2">Undone by {who.name ?? "qbrix"}.</p>
        <div>
          <Button variant="secondary" onClick={() => onOpen(id)}>
            <ArrowRight size={13} className="text-n-text-2" />
            Open the undo
          </Button>
        </div>
      </RailSection>
    );
  }
  if (entry.count > 1) {
    return (
      <RailSection title="Undo">
        <p className="n-body text-n-text-2">
          {foldOpen ? "Undo one of these changes from its own row." : "Show these changes to undo one of them."}
        </p>
        {!foldOpen && (
          <div>
            <Button variant="secondary" onClick={onExpand}>
              Show all {entry.count}
            </Button>
          </div>
        )}
      </RailSection>
    );
  }
  if (!canUndo(entry)) {
    return (
      <RailSection title="Undo">
        <p className="n-body text-n-text-2">
          {entry.not_undoable_reason ? asSentence(entry.not_undoable_reason) : "This change can't be undone."}
        </p>
      </RailSection>
    );
  }
  if (refusal?.kind === "moved") {
    return (
      <RailSection title="Undo">
        <Moved laterId={refusal.laterId} onOpen={onOpen} />
      </RailSection>
    );
  }
  return (
    <RailSection title="Undo">
      {refusal ? (
        <div role="alert" className="flex flex-col gap-1 rounded-n-panel bg-n-part-bg p-3">
          <p className="n-body font-medium text-n-part-fg">Can&apos;t undo this one.</p>
          <p className="n-meta text-n-text-1">{asSentence(refusal.detail)}</p>
        </div>
      ) : (
        <>
          {consequence && <p className="n-body text-n-text-1">{consequence}</p>}
          <p className="n-meta text-n-text-2">
            Writes the inverse as a new change, with your reason. Refused if something later moved the same thing.
          </p>
          <TextField
            ref={reasonField}
            label="Why undo?"
            hideLabel
            placeholder="Why undo? Optional"
            value={reason}
            disabled={pending}
            onChange={(event) => onReason(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                onUndo();
              }
              if (event.key === "Escape") onDismiss();
            }}
          />
          <div>
            <Button disabled={pending} onClick={onUndo}>
              <Undo2 size={13} />
              {undoLabel(entry)}
            </Button>
          </div>
        </>
      )}
    </RailSection>
  );
}

export function ChangePanel({
  entry,
  canEdit,
  refusal,
  reason,
  pending,
  foldOpen,
  confirming,
  now,
  onReason,
  onUndo,
  onDismiss,
  onOpen,
  onExpand,
}: {
  entry: ChangeEntry;
  canEdit: boolean;
  refusal: Refusal | null;
  reason: string;
  pending: boolean;
  foldOpen: boolean;
  confirming: { id: string } | null;
  now: number;
  onReason: (reason: string) => void;
  onUndo: () => void;
  onDismiss: () => void;
  onOpen: (id: string) => void;
  onExpand: () => void;
}) {
  return (
    <>
      <div className="flex flex-col gap-2">
        <span className="n-label self-start rounded-n-chip bg-n-fill-2 px-1.5 py-0.5 font-n-mono font-normal text-n-text-2">
          {entry.kind}
        </span>
        <h2 className="n-support font-medium text-n-text-1">{sentence(entry)}</h2>
        <p className="n-meta text-n-text-3">{panelTime(entry, now)}</p>
      </div>
      <Who entry={entry} />
      {entry.reason && (
        <RailSection title="Why">
          <p className="n-body text-n-text-1">{entry.reason}</p>
        </RailSection>
      )}
      <WhatChanged entry={entry} />
      {canEdit && (
        <UndoSection
          entry={entry}
          refusal={refusal}
          reason={reason}
          pending={pending}
          foldOpen={foldOpen}
          confirming={confirming}
          onReason={onReason}
          onUndo={onUndo}
          onDismiss={onDismiss}
          onOpen={onOpen}
          onExpand={onExpand}
        />
      )}
      <AskYourAgent label="Or ask your agent" prompts={[askAbout(entry)]} className="mt-auto" />
    </>
  );
}

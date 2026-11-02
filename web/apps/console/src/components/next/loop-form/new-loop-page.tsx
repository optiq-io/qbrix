"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ActorRef } from "@qbrix/ui/next/entity";
import { Field, MonoField, TextArea } from "@qbrix/ui/next/field";
import { ObjectPage } from "@qbrix/ui/next/object-page";
import { useFrozen } from "@qbrix/ui/next/offline";
import { StagedBar } from "@qbrix/ui/next/staged-bar";
import { routes } from "@/config/routes";
import { loops } from "@/lib/api/loops";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError } from "@/lib/api/types";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { useAuth } from "@/lib/auth/context";
import {
  createConsequence,
  fallbackNote,
  loopErrorField,
  loopKey,
  validateDraft,
  type DraftErrors,
  type LoopDraft,
  type OptionRow,
  type RowErrors,
} from "@/lib/loop/new-loop";
import { AfterCreate } from "./after-create";
import { MetricSection } from "./metric-section";
import { OptionsTable } from "./options-table";
import { Section } from "./section";

const CRUMBS = [{ label: "Loops", href: routes.next.home }, { label: "New loop" }];

function blankRow(id: string): OptionRow {
  return { id, name: "", key: null, config: "" };
}

const BLANK: LoopDraft = {
  name: "",
  key: null,
  purpose: "",
  options: [blankRow("0"), blankRow("1")],
  fallback: null,
  metric: null,
};

export function NewLoopPage() {
  const { user } = useAuth();

  if (user?.role === "viewer") {
    return (
      <ObjectPage crumbs={CRUMBS} canEdit={false} viewOnly="Ask an admin or a member to create loops" rail={null}>
        <p className="n-body text-n-text-2">
          Viewers can read loops but not create them.{" "}
          <Link href={routes.next.home} className="text-n-text-1 underline underline-offset-2">
            Back to loops
          </Link>
        </p>
      </ObjectPage>
    );
  }

  return <NewLoopForm ownerName={user?.name ?? "You"} />;
}

function NewLoopForm({ ownerName }: { ownerName: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const showError = useApiErrorToast();
  const frozen = useFrozen();
  const [draft, setDraft] = useState<LoopDraft>(BLANK);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [refusals, setRefusals] = useState(0);
  const nextRow = useRef(BLANK.options.length);
  const formRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (refusals > 0) formRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
  }, [refusals]);

  const refuse = (found: DraftErrors) => {
    setErrors(found);
    setRefusals((count) => count + 1);
  };

  const create = useMutation({
    mutationFn: loops.create,
    onSuccess: (loop) => {
      queryClient.setQueryData(queryKeys.loops.detail(loop.key), loop);
      queryClient.invalidateQueries({ queryKey: queryKeys.loops.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.metrics.all });
      router.push(routes.next.loop(loop.key));
    },
    onError: (error) => {
      const placed = error instanceof ApiError ? loopErrorField(error) : null;
      if (placed) refuse({ [placed.field]: placed.message });
      else showError(error);
    },
  });

  const edit = (patch: Partial<LoopDraft>, field: "name" | "key" | "metric") => {
    setDraft((current) => ({ ...current, ...patch }));
    setErrors(({ [field]: _, ...rest }) => rest);
  };

  const editRow = (id: string, patch: Partial<OptionRow>, field: keyof RowErrors) => {
    setDraft((current) => ({
      ...current,
      options: current.options.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    }));
    setErrors(({ options: _, rows, ...rest }) => {
      if (!rows?.[id]) return { ...rest, rows };
      const { [field]: _cleared, ...rowRest } = rows[id];
      return { ...rest, rows: { ...rows, [id]: rowRest } };
    });
  };

  const addRow = () => {
    const id = String(nextRow.current);
    nextRow.current += 1;
    setDraft((current) => ({ ...current, options: [...current.options, blankRow(id)] }));
  };

  const removeRow = (id: string) => {
    setDraft((current) => ({
      ...current,
      options: current.options.filter((row) => row.id !== id),
      fallback: current.fallback === id ? null : current.fallback,
    }));
    setErrors(({ options: _, ...rest }) => rest);
  };

  const submit = () => {
    const checked = validateDraft(draft);
    if (checked.errors) refuse(checked.errors);
    else create.mutate(checked.body);
  };

  const key = loopKey(draft);

  return (
    <ObjectPage
      crumbs={CRUMBS}
      rail={<AfterCreate loopKey={key} />}
      staged={
        <StagedBar
          label="New loop"
          action="Create draft"
          changes={[{ summary: "New loop", consequence: createConsequence(draft) }]}
          applying={create.isPending}
          canEdit={!frozen}
          onReview={() => undefined}
          onDiscard={() => router.push(routes.next.home)}
          onApply={submit}
        />
      }
    >
      <div ref={formRef} className="flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <Field hideLabel label="Name" error={errors.name}>
            {({ id, describedBy, invalid }) => (
              <input
                id={id}
                autoFocus
                maxLength={255}
                placeholder="Name this loop"
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
                value={draft.name}
                onChange={(event) => edit({ name: event.target.value }, "name")}
                className="n-lead w-full border-b border-transparent bg-transparent font-semibold text-n-text-1 outline-none transition-colors placeholder:text-n-text-3 hover:border-n-line focus:border-n-text-1 aria-invalid:border-n-no-fg"
              />
            )}
          </Field>
          <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
            <MonoField
              hideLabel
              label="Key"
              className="w-[280px]"
              placeholder="the-key-your-code-calls"
              value={key}
              error={errors.key}
              onChange={(event) => edit({ key: event.target.value || null }, "key")}
            />
            <span className="n-meta flex h-8 items-center gap-3 text-n-text-3">
              the key can change until launch
              <span className="flex items-center gap-1.5 text-n-text-2">
                <span aria-hidden className="size-1.5 rounded-full bg-n-text-3" />
                Not created yet
              </span>
            </span>
          </div>
        </div>

        <Section title="Purpose">
          <TextArea
            hideLabel
            label="Purpose"
            rows={2}
            placeholder="Help mobile visitors finish checkout. The headline above the pay button."
            value={draft.purpose}
            onChange={(event) => setDraft((current) => ({ ...current, purpose: event.target.value }))}
          />
        </Section>

        <Section title="Options" note="the config is what your app receives">
          <OptionsTable
            draft={draft}
            errors={errors.rows}
            onRowChange={editRow}
            onFallback={(id) => setDraft((current) => ({ ...current, fallback: id }))}
            onAdd={addRow}
            onRemove={removeRow}
          />
          {errors.options && <p className="n-label font-normal text-n-no-fg">{errors.options}</p>}
          <p className="n-meta rounded-n-control bg-n-fill-1 px-3 py-2 text-n-text-2">{fallbackNote(draft)}</p>
        </Section>

        <MetricSection
          value={draft.metric}
          error={errors.metric}
          onChange={(metric) => edit({ metric }, "metric")}
        />

        <section className="flex items-center gap-6">
          <h2 className="n-body font-semibold text-n-text-1">Owner</h2>
          <ActorRef actor={{ kind: "member", name: ownerName }} className="n-body" />
          <span className="n-meta text-n-text-3">You, as the creator</span>
        </section>
      </div>
    </ObjectPage>
  );
}

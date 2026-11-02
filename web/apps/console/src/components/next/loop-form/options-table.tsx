"use client";

import { Circle, CircleDot, Plus, X } from "lucide-react";
import { Button, IconButton } from "@qbrix/ui/next/button";
import { MonoField, TextField } from "@qbrix/ui/next/field";
import { fallbackRow, optionKeys, type LoopDraft, type OptionRow, type RowErrors } from "@/lib/loop/new-loop";

const GRID = "grid grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)_minmax(0,1.7fr)_30px] gap-4";
const QUIET_CONTROL = "[&_:is(input,textarea):not([aria-invalid]):not(:focus):not(:hover)]:border-transparent";

export function OptionsTable({
  draft,
  errors,
  onRowChange,
  onFallback,
  onAdd,
  onRemove,
}: {
  draft: LoopDraft;
  errors: Record<string, RowErrors> | undefined;
  onRowChange: (id: string, patch: Partial<OptionRow>, field: keyof RowErrors) => void;
  onFallback: (id: string) => void;
  onAdd: () => void;
  onRemove: (id: string) => void;
}) {
  const keys = optionKeys(draft.options);
  const fallback = fallbackRow(draft) ?? draft.options[0];

  return (
    <div role="radiogroup" aria-label="Fallback option" className="rounded-n-panel border border-n-line">
      <div className={`${GRID} rounded-t-n-panel border-b border-n-line-2 bg-n-bg px-3 py-2 n-label font-normal text-n-text-3`}>
        <span>Option</span>
        <span>Key</span>
        <span>Config</span>
      </div>
      {draft.options.map((row, at) => {
        const isFallback = row.id === fallback?.id;
        const Icon = isFallback ? CircleDot : Circle;
        const rowErrors = errors?.[row.id];
        return (
          <div key={row.id} className={`${GRID} items-start border-b border-n-line-2 px-3 py-1.5`}>
            <div className="flex items-start gap-1.5">
              <label title="Use as the fallback" className="relative mt-2.5 flex shrink-0 cursor-pointer text-n-text-3 hover:text-n-text-1">
                <input
                  type="radio"
                  name="fallback"
                  value={row.id}
                  checked={isFallback}
                  aria-label={`Use ${row.name.trim() || `option ${at + 1}`} as the fallback`}
                  onChange={() => onFallback(row.id)}
                  className="peer sr-only"
                />
                <Icon size={12} className={`rounded-full peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-n-ink ${isFallback ? "text-n-text-1" : ""}`} />
              </label>
              <TextField
                hideLabel
                label={`Option ${at + 1} name`}
                placeholder={at === 0 ? "Pay in one tap" : "Option name"}
                maxLength={255}
                value={row.name}
                error={rowErrors?.name}
                className={`min-w-0 flex-1 ${QUIET_CONTROL}`}
                onChange={(event) => onRowChange(row.id, { name: event.target.value }, "name")}
              />
            </div>
            <MonoField
              hideLabel
              label={`Option ${at + 1} key`}
              placeholder="key"
              value={keys.get(row.id) ?? ""}
              error={rowErrors?.key}
              className={QUIET_CONTROL}
              onChange={(event) => onRowChange(row.id, { key: event.target.value || null }, "key")}
            />
            <MonoField
              multiline
              hideLabel
              rows={1}
              label={`Option ${at + 1} config`}
              placeholder={'{ "headline": "Pay in one tap" }'}
              value={row.config}
              error={rowErrors?.config}
              className={QUIET_CONTROL}
              onChange={(event) => onRowChange(row.id, { config: event.target.value }, "config")}
            />
            {draft.options.length > 1 ? (
              <IconButton aria-label={`Remove option ${at + 1}`} onClick={() => onRemove(row.id)} className="text-n-text-3">
                <X size={13} />
              </IconButton>
            ) : (
              <span />
            )}
          </div>
        );
      })}
      <div className="px-1.5 py-1">
        <Button variant="quiet" size="sm" onClick={onAdd} className="text-n-text-3">
          <Plus size={13} />
          Add option
        </Button>
      </div>
    </div>
  );
}

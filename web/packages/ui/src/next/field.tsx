"use client";

import { useId } from "react";
import { cn } from "../lib/utils";

export const CONTROL =
  "w-full rounded-n-control border border-n-line bg-n-surface px-2.5 py-1.5 text-n-text-1 outline-none transition-colors placeholder:text-n-text-3 focus:border-n-text-1 aria-invalid:border-n-no-fg";

type FieldFrame = {
  label: string;
  hint?: string;
  /** replaces the hint while it's set */
  error?: string;
  /** false for a person who can't make this change: the field is absent, never disabled */
  canEdit?: boolean;
};

/** label, control, then a hint or an error, linked for screen readers */
export function Field({
  label,
  hint,
  error,
  className,
  children,
}: FieldFrame & {
  className?: string;
  children: (ids: { id: string; describedBy?: string; invalid: boolean }) => React.ReactNode;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error ?? hint;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="n-meta font-medium text-n-text-3">
        {label}
      </label>
      {children({ id, describedBy: note ? noteId : undefined, invalid: Boolean(error) })}
      {note && (
        <p
          id={noteId}
          className={cn("n-label font-normal", error ? "text-n-no-fg" : "text-n-text-3")}
        >
          {note}
        </p>
      )}
    </div>
  );
}

type InputProps = FieldFrame & Omit<React.ComponentProps<"input">, "id">;
type AreaProps = FieldFrame & Omit<React.ComponentProps<"textarea">, "id">;

export function TextField({ label, hint, error, canEdit = true, className, ...props }: InputProps) {
  if (!canEdit) return null;
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {({ id, describedBy, invalid }) => (
        <input
          id={id}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          className={cn(CONTROL, "n-body")}
          {...props}
        />
      )}
    </Field>
  );
}

export function TextArea({ label, hint, error, canEdit = true, className, rows = 3, ...props }: AreaProps) {
  if (!canEdit) return null;
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {({ id, describedBy, invalid }) => (
        <textarea
          id={id}
          rows={rows}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          className={cn(CONTROL, "n-body resize-y")}
          {...props}
        />
      )}
    </Field>
  );
}

/** keys, identifiers and JSON config; `multiline` for JSON */
export function MonoField(
  props: (InputProps & { multiline?: false }) | (AreaProps & { multiline: true }),
) {
  if (props.multiline) {
    const { multiline: _, className, ...rest } = props;
    return <TextArea {...rest} className={cn("[&_textarea]:n-mono", className)} spellCheck={false} />;
  }
  const { multiline: _, className, ...rest } = props;
  return (
    <TextField
      {...rest}
      className={cn("[&_input]:n-mono", className)}
      spellCheck={false}
      autoCapitalize="off"
      autoComplete="off"
    />
  );
}

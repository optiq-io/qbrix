import { TriangleAlert } from "lucide-react";
import { cn } from "../lib/utils";
import { StateActions } from "./state-actions";

// board `APP · Empty, loading & error states` / `EXPERIMENTS · ERROR`.
//
// deliberately the same skeleton as `EmptyState` — icon, title, description,
// `StateActions` — because the board draws them as one panel with a different
// centre. the only additions are the danger tint and the code chip.
//
// this exists because a failed list query used to render as an *empty* list,
// which is indistinguishable from "you have none" and quietly wrong.

export function ErrorState({
  title,
  description,
  /** the API's own words — status line, error code. omitted when there is none
      worth showing; never invent one. */
  code,
  onRetry,
  className,
}: {
  title: string;
  description: string;
  code?: string | null;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-[26px] py-20",
        className,
      )}
    >
      <div className="flex size-[46px] items-center justify-center rounded-[12px] border border-danger/20 bg-danger/[0.08]">
        <TriangleAlert size={19} className="text-danger" />
      </div>

      <h3 className="pt-5 text-center text-[15.5px] font-semibold leading-tight tracking-[-0.2px] text-text-primary">
        {title}
      </h3>
      <p className="max-w-[404px] pt-[9px] text-center text-[12.5px] leading-[1.55] text-text-dim">
        {description}
      </p>

      {code && (
        <span className="mt-3 rounded-md border border-border bg-bg-panel px-[9px] py-1 font-mono text-[10.5px] text-text-faint">
          {code}
        </span>
      )}

      {onRetry && (
        <StateActions
          className="pt-5"
          primary={{ label: "Try again", onClick: onRetry }}
        />
      )}
    </div>
  );
}

import { ApiError } from "./types";
import { errorRegistry, type ErrorAction } from "./error-registry";

export type ResolvedApiError = {
  title?: string;
  message: string;
  hint?: string;
  action?: ErrorAction;
  code?: string;
  status?: number;
};

// the mono chip on `ErrorState` — board `APP · Empty, loading & error states`
// draws it as `503 · upstream unavailable`. it is the API's own words, so it
// returns null rather than inventing a code when the failure came from
// somewhere else (a dropped connection has no status).
export function apiErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const detail = err.code ?? err.detail;
  return detail ? `${err.status} · ${detail}` : String(err.status);
}

export function resolveApiError(err: unknown, fallback?: string): ResolvedApiError {
  if (err instanceof ApiError) {
    const entry = err.code ? errorRegistry[err.code] : undefined;

    if (entry) {
      return {
        title: entry.title,
        message: entry.description?.(err.detail, err.context) ?? err.detail,
        hint: entry.hint,
        action: entry.action,
        code: err.code,
        status: err.status,
      };
    }

    return {
      message: err.detail,
      code: err.code,
      status: err.status,
    };
  }

  return { message: fallback ?? "Something went wrong" };
}

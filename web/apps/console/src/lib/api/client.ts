import * as Sentry from "@sentry/nextjs";

import { getAccessToken, getRefreshToken, storeTokens, clearTokens } from "../auth/tokens";
import { ApiError } from "./types";

// same-origin unless overridden: every host serving the console routes /api to
// the proxy. `||`, not `??` — an image built without the arg inlines "".
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

// resource ids are `uuid4().hex` — 32 hex chars, no dashes
const RESOURCE_ID = /^[0-9a-f]{32}$/i;

/** ids in a tag value would give every experiment its own group, which is the
    fastest way to make sentry's grouping useless. */
function endpointTag(path: string): string {
  return path
    .split("?")[0]
    .split("/")
    .map((segment) => (RESOURCE_ID.test(segment) ? ":id" : segment))
    .join("/");
}

let isRefreshing = false;

// the `(auth)` route group — every one of these is reached while signed out
const SIGNED_OUT_ROUTES = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/invite",
];

function isSignedOutRoute(pathname: string): boolean {
  return SIGNED_OUT_ROUTES.some((route) => pathname.startsWith(route));
}

async function tryRefreshToken(): Promise<boolean> {
  if (isRefreshing) return false;
  isRefreshing = true;
  try {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return false;

    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (res.ok) {
      const data = await res.json();
      if (data.access_token) {
        storeTokens(data.access_token, refreshToken);
        return true;
      }
    }
    clearTokens();
    return false;
  } catch {
    return false;
  } finally {
    isRefreshing = false;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAccessToken();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(token && { Authorization: `Bearer ${token}` }),
        ...options?.headers,
      },
    });
  } catch (err) {
    // the request never reached the api: offline, dns, tls, cors
    Sentry.captureException(err, { tags: { endpoint: endpointTag(path) } });
    throw err;
  }

  if (res.status === 401) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      return apiFetch<T>(path, options);
    }
    // redirect to login on auth failure, but never from a route that is
    // *meant* to be visited signed out. AuthProvider probes /auth/profile on
    // every page, so before this list covered them a verification or invite
    // link bounced straight to sign in — and you cannot sign in until you have
    // followed the link, which deadlocks the whole signup.
    if (typeof window !== "undefined" && !isSignedOutRoute(window.location.pathname)) {
      const redirect = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?redirect=${redirect}`;
    }
    let detail = "authentication required";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new ApiError(401, detail);
  }

  if (!res.ok) {
    let detail = "request failed";
    let code: string | undefined;
    let context: Record<string, unknown> | undefined;
    try {
      const body = await res.json();
      // fastapi 422 returns detail as an array of pydantic validation errors
      if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((e: { loc?: string[]; msg?: string }) =>
            e.loc ? `${e.loc.slice(1).join(".")}: ${e.msg}` : (e.msg ?? "validation error"),
          )
          .join("; ");
      } else {
        detail = typeof body.detail === "string" ? body.detail : detail;
      }
      code = typeof body.code === "string" ? body.code : undefined;
      context = body.context && typeof body.context === "object" ? body.context : undefined;
    } catch {}
    const header = res.headers.get("Retry-After");
    const parsed = header ? Number(header) : NaN;
    const error = new ApiError(
      res.status,
      detail,
      code,
      context,
      Number.isFinite(parsed) ? parsed : undefined,
    );
    // 4xx is the user or the domain talking — it already toasts, and reporting
    // it would spend the quota on expected outcomes.
    if (res.status >= 500) {
      Sentry.captureException(error, {
        tags: { endpoint: endpointTag(path), status: res.status },
      });
    }
    throw error;
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return res.json();
}

export function buildQueryString(params: Record<string, unknown> = {}): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  }
  const qs = searchParams.toString();
  return qs ? `?${qs}` : "";
}

"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { useRef, useState } from "react";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";

// bump when a cached shape changes in a way an old entry cannot satisfy. the
// whole cache is dropped rather than migrated — it is a copy of the API, never
// a source of truth, and one request rebuilds it.
const CACHE_BUSTER = "v1";

const ONE_HOUR = 1000 * 60 * 60;

const CACHE_KEY = "qbrix.console.query-cache";

/** drop the restored copy as well as the live one. `queryClient.clear()` alone
    empties memory and then the next persist tick writes it back out — and even
    if it did not, a reload would restore the previous tenant's rows. */
export function purgeQueryCache(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(CACHE_KEY);
  } catch {}
}

// sessionStorage, not localStorage, and that is the deliberate half of this.
//
// the cache holds a workspace's experiments, pools and analytics. sessionStorage
// is per-tab and dies with the tab, so it cannot outlive a sign-out in another
// tab, cannot be read by the next person on a shared machine, and cannot serve
// one tenant's rows to the account someone signs in as next. what it buys is the
// case that actually matters — a reload, a back navigation, a re-entry from
// Stripe — painting from the last known answer instead of a skeleton.
function buildPersister() {
  if (typeof window === "undefined") return undefined;
  return createSyncStoragePersister({
    storage: window.sessionStorage,
    key: CACHE_KEY,
    // a quota failure is not worth an error: the app is correct without the
    // cache, it is only slower.
    retry: () => undefined,
  });
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const handleApiError = useApiErrorToast();
  const handlerRef = useRef(handleApiError);
  handlerRef.current = handleApiError;

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1000 * 60 * 5, // 5 minutes
            retry: 1,
            // must exceed the persister's maxAge or a restored entry is
            // garbage-collected on the first tick, before it can be shown.
            gcTime: ONE_HOUR,
          },
          mutations: {
            onError: (err) => handlerRef.current(err),
          },
        },
      }),
  );

  const [persister] = useState(buildPersister);

  // server render: there is no storage to restore from, so the plain provider
  // — PersistQueryClientProvider has no valid no-op persister to be given.
  if (!persister) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister,
        maxAge: ONE_HOUR,
        buster: CACHE_BUSTER,
        dehydrateOptions: {
          // only successful queries are worth restoring. a persisted error
          // would reproduce a transient failure on the next load and make it
          // look permanent.
          shouldDehydrateQuery: (query) =>
            query.state.status === "success" &&
            // never persist an identity. the shell reads the user from
            // AuthProvider, and a restored profile could outlive the token
            // that earned it.
            query.queryKey[0] !== "auth",
        },
      }}
    >
      {children}
    </PersistQueryClientProvider>
  );
}

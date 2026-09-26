"use client";

import * as Sentry from "@sentry/nextjs";
import { ErrorBoundary } from "@qbrix/ui/components/error-boundary";

/** the reporting half of @qbrix/ui's ErrorBoundary. it lives here rather than in
    the shared package so that package keeps no error-tracking dependency, and
    because a server layout cannot pass a function prop to a client component. */
export function ErrorReportingBoundary({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary
      onError={(error, errorInfo) =>
        Sentry.captureException(error, {
          contexts: { react: { componentStack: errorInfo.componentStack } },
        })
      }
    >
      {children}
    </ErrorBoundary>
  );
}

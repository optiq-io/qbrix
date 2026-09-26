"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import { AlertCircle, RotateCw } from "lucide-react";
import { fontVariables } from "@qbrix/ui/fonts";

import "./globals.css";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en" className={fontVariables}>
      <body>
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-danger/10">
            <AlertCircle size={24} className="text-danger" />
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <span className="font-heading text-base font-bold text-text-primary">
              Something went wrong
            </span>
            <span className="max-w-md text-center text-[13px] text-text-secondary">
              The console hit an unexpected error and could not continue.
            </span>
          </div>
          <button
            onClick={reset}
            className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-[13px] font-medium text-text-secondary transition-colors hover:border-text-dim hover:text-text-primary"
          >
            <RotateCw size={14} />
            <span>Try again</span>
          </button>
        </div>
      </body>
    </html>
  );
}

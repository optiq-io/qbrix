"use client";

import { notFound, useSearchParams } from "next/navigation";
import { useDeployment } from "@/lib/deployment";
import { AuthGuard } from "@/lib/auth/guard";
import { Approval } from "./approval";
import { AuthorizeExpired, AuthorizeLoading } from "./frame";

// gated on the server's switch, not the build flag: the approval API exists
// only when the proxy runs next, whatever image the console was built from
export function Authorize() {
  const { next, isLoading } = useDeployment();
  const requestId = useSearchParams().get("request");

  if (!isLoading && !next) notFound();

  return (
    <div data-console="next" className="min-h-screen bg-n-bg">
      {isLoading ? (
        <AuthorizeLoading />
      ) : (
        <AuthGuard fallback={<AuthorizeLoading />}>
          {requestId ? <Approval requestId={requestId} /> : <AuthorizeExpired />}
        </AuthGuard>
      )}
    </div>
  );
}

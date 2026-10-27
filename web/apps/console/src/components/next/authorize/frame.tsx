import { Button } from "@qbrix/ui/next/button";

export function AuthorizeFrame({
  workspace,
  footnote,
  children,
}: {
  workspace?: string;
  footnote?: string;
  children: React.ReactNode;
}) {
  return (
    <main className="flex flex-col items-center gap-5 px-4 pb-12 pt-24">
      {workspace && (
        <div className="flex items-center gap-2">
          <span aria-hidden className="size-[22px] rounded-n-control bg-n-ink" />
          <span className="text-[14px] font-semibold text-n-text-1">{workspace}</span>
          <span className="n-body text-n-text-3">on qbrix</span>
        </div>
      )}
      <section className="flex w-full max-w-[480px] flex-col gap-5 rounded-n-panel border border-n-line bg-n-surface p-7">
        {children}
      </section>
      {footnote && <p className="n-meta max-w-[480px] text-center text-n-text-3">{footnote}</p>}
    </main>
  );
}

export function AuthorizeTitle({ children }: { children: React.ReactNode }) {
  return (
    <h1 className="text-[20px] font-semibold leading-[1.3] text-n-text-1">{children}</h1>
  );
}

function Bar({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-n-chip bg-n-fill-2 ${className}`} />;
}

export function AuthorizeLoading() {
  return (
    <AuthorizeFrame>
      <div aria-busy className="flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <Bar className="h-[26px] w-4/5" />
          <Bar className="h-4 w-2/5" />
        </div>
        <Bar className="h-10 w-full" />
        <Bar className="h-[42px] w-full" />
        <Bar className="h-[33px] w-40" />
      </div>
    </AuthorizeFrame>
  );
}

export function AuthorizeExpired({ client }: { client?: string }) {
  return (
    <AuthorizeFrame>
      <AuthorizeTitle>This request has expired or was already answered.</AuthorizeTitle>
      <p className="n-body text-n-text-2">
        Start signing in again from {client ?? "your client"}.
      </p>
    </AuthorizeFrame>
  );
}

export function AuthorizeDone({
  client,
  approved,
  workspace,
}: {
  client: string;
  approved: boolean;
  workspace?: string;
}) {
  return (
    <AuthorizeFrame workspace={workspace}>
      <AuthorizeTitle>{approved ? `${client} is connected` : "Connection cancelled"}</AuthorizeTitle>
      <p className="n-body text-n-text-2">Go back to {client}. This tab can be closed.</p>
    </AuthorizeFrame>
  );
}

export function AuthorizeUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <AuthorizeFrame>
      <AuthorizeTitle>This sign-in request couldn&apos;t be loaded.</AuthorizeTitle>
      <div>
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      </div>
    </AuthorizeFrame>
  );
}

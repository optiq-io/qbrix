import { QbrixBrick } from "@qbrix/ui/components/logo";
import { Skeleton } from "@qbrix/ui/components/skeleton";

// what the console looks like while it is still finding out who you are.
//
// the auth probe sits above every page, so until it answers there is no shell
// to hang a page skeleton on — and what stood here was the string "loading…"
// centred on an empty screen, which is the one moment of the whole session with
// no console in it at all.
//
// this is the shell's own geometry: the 64px rail, the 62px topbar hairline,
// the same left inset the real `main` uses. the chrome does not move when the
// real one replaces it, so the sign-in → home path draws the console once and
// then fills it, rather than cutting from a blank screen to a full page.
export function AppShellSkeleton() {
  return (
    <div className="min-h-screen bg-bg">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-16 flex-col items-center gap-1 border-r border-border-subtle bg-bg py-[14px] lg:flex">
        {/* the mark is the one thing here that is not a guess — it is the same
            at every stage of loading, so it is drawn for real */}
        <QbrixBrick size={30} />
        <div className="h-2" />
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="size-9 rounded-[10px]" />
        ))}
        <div className="flex-1" />
        <Skeleton className="size-9 rounded-full" />
      </aside>

      <main className="flex min-h-[calc(100vh-52px)] flex-col bg-bg pt-[52px] lg:min-h-screen lg:pl-16 lg:pt-0">
        <div className="sticky top-0 z-30 hidden h-[62px] shrink-0 items-center border-b border-border-subtle bg-bg px-7 lg:flex">
          <Skeleton className="h-[15px] w-[112px]" />
        </div>
      </main>
    </div>
  );
}

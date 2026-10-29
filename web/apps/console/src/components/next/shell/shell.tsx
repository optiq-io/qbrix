"use client";

import { usePathname } from "next/navigation";
import { NextRoot } from "@qbrix/ui/next/root";
import { cn } from "@qbrix/ui/lib/utils";
import { AuthGuard } from "@/lib/auth/guard";
import { LargerScreen } from "./larger-screen";
import { phoneAllowed } from "./nav";
import { Sidebar } from "./sidebar";

export function NextShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const onPhone = phoneAllowed(pathname);

  return (
    <NextRoot>
      <AuthGuard fallback={<ShellLoading />}>
        <Sidebar />
        {!onPhone && <LargerScreen />}
        <main className={cn("min-h-screen min-w-0 flex-col lg:flex lg:pl-[232px]", onPhone ? "flex" : "hidden")}>
          {children}
        </main>
      </AuthGuard>
    </NextRoot>
  );
}

function ShellLoading() {
  return (
    <div
      aria-hidden
      className="fixed inset-y-0 left-0 hidden w-[232px] border-r border-n-line-2 bg-n-bg lg:block"
    />
  );
}

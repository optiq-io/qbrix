"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { LargerScreen } from "@qbrix/ui/next/larger-screen";
import { routes } from "@/config/routes";
import { largerScreenTitle } from "./nav";

export function LargerScreenPage() {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen flex-col lg:hidden">
      <Link href={routes.next.inbox} className="flex items-center gap-1 px-3 pt-3 pb-2 text-[15px] text-n-text-2">
        <ChevronLeft size={18} />
        Inbox
      </Link>
      <div className="flex flex-1 flex-col justify-end p-4">
        <LargerScreen title={largerScreenTitle(pathname)} />
      </div>
    </div>
  );
}

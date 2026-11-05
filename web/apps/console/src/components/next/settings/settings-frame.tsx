"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { useWorkspace } from "@/components/next/shell/data";
import { settingsHref, settingsSections, type SettingsScope } from "./section";

const CAPTION: Record<SettingsScope, (workspace: string) => string> = {
  you: () => "Only you see these.",
  workspace: (workspace) => `Shared by everyone in ${workspace}. Admins change them.`,
};

export function SettingsFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data } = useWorkspace();
  const workspace = data ? data.name || data.slug : "";
  const scopeName = (scope: SettingsScope) => (scope === "you" ? "You" : workspace);

  const [scope, slug] = pathname.split("/").slice(3) as [SettingsScope | undefined, string | undefined];
  const current = scope && settingsSections[scope]?.find((section) => section.slug === slug);

  return (
    <div className="flex min-h-screen flex-col">
      <nav aria-label="Breadcrumb" className="flex h-[52px] shrink-0 items-center gap-2 px-6 n-body">
        {scope && current && (
          <>
            <span className="text-n-text-2">{scopeName(scope)}</span>
            <ChevronRight size={13} className="text-n-text-3" />
            <span aria-current="page" className="text-n-text-1">
              {current.label}
            </span>
          </>
        )}
      </nav>

      <div className="flex flex-1">
        <nav aria-label="Settings" className="flex w-[220px] shrink-0 flex-col gap-0.5 px-3 py-6">
          {(Object.keys(settingsSections) as SettingsScope[]).map((group) => (
            <div key={group} className="flex flex-col gap-0.5">
              <div className="flex flex-col gap-0.5 px-2 pt-3 pb-1 n-label font-normal text-n-text-3">
                <span>{scopeName(group)}</span>
                <span>{CAPTION[group](workspace)}</span>
              </div>
              {settingsSections[group].map((section) => {
                const active = group === scope && section.slug === slug;
                return (
                  <Link
                    key={section.slug}
                    href={settingsHref(group, section.slug)}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "rounded-n-control px-2 py-[5px] n-body text-n-text-2 hover:bg-n-fill-1",
                      active && "bg-n-fill-2 font-medium text-n-text-1 hover:bg-n-fill-2",
                    )}
                  >
                    {section.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="min-w-0 flex-1 px-12 py-8">
          <div className="flex max-w-[760px] flex-col gap-6">{children}</div>
        </div>
      </div>
    </div>
  );
}

export function SettingsTitle({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h1 className="text-[22px] font-semibold leading-tight text-n-text-1">{title}</h1>
      {children && <p className="n-body text-n-text-2">{children}</p>}
    </div>
  );
}

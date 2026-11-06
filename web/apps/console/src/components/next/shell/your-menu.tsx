"use client";

import { BookOpen, Keyboard, LogIn, LogOut, Plug, Plus, Sparkles, SunMoon, UserCog } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { routes } from "@/config/routes";
import { useAuth } from "@/lib/auth/context";
import { connectionHealth, connectionNote, plugHealth } from "@/lib/connection/health";
import { settingsHref, yourSettingsHome } from "@/components/next/settings/section";
import { useTheme } from "@qbrix/ui/lib/theme";
import { THEME_OPTIONS } from "@/components/next/settings/theme-switch";
import { openShortcuts } from "./command";
import { useMinute, useYourConnections } from "./data";
import { EndMenu, MenuDivider, MenuRow } from "./end-menu";

const DOCS = "https://qbrix.io/docs";
const WHATS_NEW = "https://github.com/optiq-io/qbrix/releases";

export function YourMenu() {
  const { user, logout } = useAuth();
  const { data: connections = [] } = useYourConnections();
  const now = useMinute();
  const name = user?.name || user?.email.split("@")[0] || "";
  const initial = name.charAt(0).toUpperCase();

  const signOut = async () => {
    await logout();
    window.location.assign(routes.login);
  };

  return (
    <EndMenu
      label="You"
      opens="up"
      width={296}
      trigger={
        <>
          <span className="flex size-[22px] shrink-0 items-center justify-center rounded-full bg-n-fill-2 text-[11px] font-semibold text-n-text-2">
            {initial}
          </span>
          <span className="min-w-0 flex-1 truncate n-body text-n-text-2">{name}</span>
          {connections.length > 0 && (
            <span
              data-slot="connections"
              aria-label={`${connections.length} connections`}
              className="flex shrink-0 items-center gap-1 rounded-n-chip px-1.5 py-0.5 text-n-text-2"
            >
              <Dot ending={plugHealth(connections, now) === "ending"} />
              <Plug size={13} />
              <span className="n-meta tabular-nums">{connections.length}</span>
            </span>
          )}
        </>
      }
    >
      {(close) => (
        <>
          <div className="flex items-center gap-2.5 px-2 pt-2 pb-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-n-fill-2 text-[13px] font-semibold text-n-text-2">
              {initial}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate n-body font-semibold text-n-text-1">{name}</span>
              <span className="truncate n-label font-normal text-n-text-3">{user?.email}</span>
            </span>
          </div>

          <MenuDivider />
          <div className="flex items-center gap-2.5 p-2">
            <SunMoon size={15} className="shrink-0 text-n-text-2" />
            <span className="flex-1 n-body text-n-text-1">Theme</span>
            <ThemeChoice />
          </div>

          <div className="flex flex-col gap-1.5 px-2 pt-2 pb-1">
            <div className="flex items-center n-label text-n-text-3">
              <span className="flex-1">Your connections</span>
              <span className="font-normal tabular-nums">{connections.length}</span>
            </div>
            {connections.map((connection) => (
              <div key={connection.id} className="flex items-center gap-2">
                <Dot ending={connectionHealth(connection, now) === "ending"} />
                <span className="min-w-0 flex-1 truncate n-meta text-n-text-1">{connection.client.name}</span>
                <span className="shrink-0 n-label font-normal text-n-text-3">{connectionNote(connection, now)}</span>
              </div>
            ))}
          </div>
          <MenuRow icon={Plus} label="Connect a client" href={settingsHref("you", "connections")} close={close} />

          <MenuDivider />
          <MenuRow icon={UserCog} label="Your settings" hint="G Y" mono href={yourSettingsHome} close={close} />
          <MenuRow icon={Keyboard} label="Keyboard shortcuts" hint="?" mono onSelect={openShortcuts} close={close} />
          <MenuRow icon={BookOpen} label="Docs" hint="↗" href={DOCS} external close={close} />
          <MenuRow icon={Sparkles} label="What's new" href={WHATS_NEW} external close={close} />

          <MenuDivider />
          <MenuRow icon={LogIn} label="Sign in to another workspace" onSelect={signOut} close={close} />
          <MenuRow icon={LogOut} label="Sign out" onSelect={signOut} close={close} />
        </>
      )}
    </EndMenu>
  );
}

function ThemeChoice() {
  const { theme, setTheme } = useTheme();
  return (
    <div role="group" aria-label="Theme" className="inline-flex gap-0.5 rounded-n-control border border-n-line p-px">
      {THEME_OPTIONS.map((option) => {
        const checked = option.value === theme;
        return (
          <button
            key={option.value}
            type="button"
            role="menuitemradio"
            aria-checked={checked}
            aria-label={option.label}
            title={option.label}
            tabIndex={-1}
            onClick={() => setTheme(option.value)}
            className={cn(
              "flex h-[22px] w-[26px] items-center justify-center rounded-n-chip outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-n-ink",
              checked ? "bg-n-fill-2 text-n-text-1" : "text-n-text-2 hover:text-n-text-1 focus:text-n-text-1",
            )}
          >
            {option.icon}
          </button>
        );
      })}
    </div>
  );
}

function Dot({ ending }: { ending: boolean }) {
  return <span className={cn("size-1.5 shrink-0 rounded-full", ending ? "bg-n-part-fg" : "bg-n-ok-fg")} />;
}

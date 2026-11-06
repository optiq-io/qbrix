"use client";

import { cn } from "@qbrix/ui/lib/utils";
import { connectionHealth, endsOn } from "@/lib/connection/health";
import { ago } from "@/lib/loop/fact";
import { useMinute, useYourConnections } from "@/components/next/shell/data";
import { SettingsTitle } from "./settings-frame";

function since(at: string) {
  return new Date(at).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function YourConnections() {
  const { data: connections, isPending } = useYourConnections();
  const now = useMinute();

  return (
    <>
      <SettingsTitle title="Your connections">
        Clients that act for you over MCP. A connection unused for 90 days ends, and its client signs in again.
      </SettingsTitle>

      {!isPending && connections?.length === 0 && (
        <p className="n-body text-n-text-3">No client acts for you yet.</p>
      )}

      {connections && connections.length > 0 && (
        <div className="flex flex-col">
          <div className="flex gap-6 pb-2 n-label font-normal text-n-text-3">
            <span className="flex-1">Connection</span>
            <span className="w-[140px]">Last used</span>
          </div>
          {connections.map((connection) => {
            const ending = connectionHealth(connection, now) === "ending";
            return (
              <div key={connection.id} className="flex gap-6 border-t border-n-line-2 py-3">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate n-body font-medium text-n-text-1">{connection.client.name}</span>
                  <span className="n-meta text-n-text-3">
                    {connection.user.name} · since {since(connection.created_at)}
                  </span>
                </div>
                <div className="flex w-[140px] flex-col gap-0.5">
                  <span className="flex items-center gap-1.5 n-body text-n-text-1">
                    <span className={cn("size-1.5 rounded-full", ending ? "bg-n-part-fg" : "bg-n-ok-fg")} />
                    {connection.last_used_at ? ago(connection.last_used_at, now) : "Not used yet"}
                  </span>
                  {ending && <span className="n-meta text-n-part-fg">Ends {endsOn(connection)}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

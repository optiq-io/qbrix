"use client";

import { usePathname } from "next/navigation";
import { NotFound } from "@qbrix/ui/next/page-error";
import { useWorkspaceName } from "@/components/shell/workspace-row";
import { redirectToLogin } from "@/lib/api/auth";
import { useAuth } from "@/lib/auth/context";
import { routes } from "@/config/routes";

export default function NextNotFound() {
  const pathname = usePathname();
  const workspace = useWorkspaceName();
  const { user, logout } = useAuth();

  if (!workspace || !user) return null;

  return (
    <NotFound
      path={pathname.replace(routes.next.home, "") || "/"}
      noun={pathname.startsWith(`${routes.next.home}/loops/`) ? "loop" : undefined}
      workspace={workspace}
      email={user.email}
      home={{ href: routes.next.home, label: "Go to loops" }}
      onSwitchAccount={async () => {
        await logout();
        redirectToLogin();
      }}
    />
  );
}

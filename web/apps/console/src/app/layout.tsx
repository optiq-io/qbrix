import type { Metadata } from "next";
import { fontVariables } from "@qbrix/ui/fonts";
import { AuthProvider } from "@/lib/auth/context";
import { QueryProvider } from "@/lib/query-provider";
import { ToastProvider } from "@qbrix/ui/components/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "qbrix",
  description: "Manage your bandit experiments, pools, and settings.",
  icons: {
    icon: "/favicon.svg",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={fontVariables}>
      <body>
        {/* AuthProvider is innermost so that signing out can clear the query
            cache: the cache is now persisted to sessionStorage, and a
            workspace's rows must not survive the session that fetched them. */}
        <ToastProvider>
          <QueryProvider>
            <AuthProvider>{children}</AuthProvider>
          </QueryProvider>
        </ToastProvider>
      </body>
    </html>
  );
}

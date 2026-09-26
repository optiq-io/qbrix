import { AuthGuard } from "@/lib/auth/guard";
import { AppShell } from "@/components/shell/app-shell";
import { ErrorReportingBoundary } from "@/lib/error-reporting-boundary";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <AppShell>
        <ErrorReportingBoundary>{children}</ErrorReportingBoundary>
      </AppShell>
    </AuthGuard>
  );
}

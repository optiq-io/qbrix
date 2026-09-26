import { Suspense } from "react";
import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/components/auth/login-form";
import { ShowcaseActivity } from "@/components/auth/showcase-activity";

export default function LoginPage() {
  return (
    <AuthShell showcase={<ShowcaseActivity />}>
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}

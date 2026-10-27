import type { Metadata } from "next";
import { Suspense } from "react";
import { Authorize } from "@/components/next/authorize/authorize";

export const metadata: Metadata = {
  title: "Connect a client · qbrix",
};

export default function AuthorizePage() {
  return (
    <Suspense>
      <Authorize />
    </Suspense>
  );
}

"use client";

import { notFound } from "next/navigation";
import { useEntitlements } from "@/lib/entitlements";

// the cloud-only routes: checkout, the stripe return pages, the plan selector
// and the /settings/billing alias. one guard rather than a check per page.
//
// it 404s only once the backend has *said* the edition is not cloud. a
// signed-out visitor has no profile, and /billing/success is reached straight
// from stripe before the session is restored — 404ing on an unknown edition
// would break that return trip.
export default function EditionLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { edition } = useEntitlements();
  if (edition !== null && edition !== "cloud") notFound();
  return <>{children}</>;
}

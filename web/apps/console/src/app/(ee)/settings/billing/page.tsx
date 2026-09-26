"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { routes } from "@/config/routes";

// /settings/billing is the URL the console IA documents; the billing surface
// itself is a tab on the guarded, shelled settings page.
//
// client-side rather than a server `redirect()` so that the (ee) guard above it
// gets to answer first — a server redirect resolves during the RSC render, and
// would forward a self-host visitor instead of 404ing.
export default function SettingsBillingPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace(routes.settingsBilling);
  }, [router]);

  return null;
}

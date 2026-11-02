import { Suspense } from "react";
import { ChangesPage } from "@/components/next/change/changes-page";
import { ChangesLoading } from "@/components/next/change/loading";

export default function Changes() {
  return (
    <Suspense fallback={<ChangesLoading />}>
      <ChangesPage />
    </Suspense>
  );
}

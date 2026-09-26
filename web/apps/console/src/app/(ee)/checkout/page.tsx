import { Suspense } from "react";
import { CheckoutPageContent } from "@/ee/components/checkout/checkout-page-content";

export default function CheckoutPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-bg" />}>
      <CheckoutPageContent />
    </Suspense>
  );
}

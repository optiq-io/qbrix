"use client";

import { useState } from "react";
import { Menu } from "@qbrix/ui/next/menu";
import { PinnedList } from "@/components/next/shell/pinned";
import type { Pin } from "@/lib/api/types";

const PINS: Pin[] = [
  { kind: "loop", ref: "1", name: "Checkout headline", key: "checkout-headline", state: "live" },
  { kind: "loop", ref: "2", name: "Search ranking", key: "search-ranking", state: "paused" },
  { kind: "loop", ref: "3", name: "Pricing page CTA", key: "pricing-page-cta", state: "draft" },
  { kind: "metric", ref: "4", name: "checkout_completed", key: "checkout_completed", state: null },
];

export function PinnedSheet() {
  const [pinned, setPinned] = useState(false);

  return (
    <div className="grid gap-6 md:grid-cols-3">
      <div className="flex flex-col gap-2">
        <span className="n-meta text-n-text-3">Pinned</span>
        <div className="w-[216px]">
          <PinnedList pins={PINS} pathname={null} />
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <span className="n-meta text-n-text-3">Nothing pinned</span>
        <div className="w-[216px]">
          <PinnedList pins={[]} pathname={null} />
        </div>
      </div>
      <div className="flex flex-col items-start gap-2">
        <span className="n-meta text-n-text-3">In a ⋯ menu</span>
        <Menu align="left" items={[{ label: pinned ? "Unpin" : "Pin", onSelect: () => setPinned((v) => !v) }]} />
      </div>
    </div>
  );
}

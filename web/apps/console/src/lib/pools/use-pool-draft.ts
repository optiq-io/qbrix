"use client";

import { useCallback, useMemo, useState } from "react";
import { pools as poolsApi } from "@/lib/api/pools";
import type { Pool } from "@/lib/api/types";

// a pool being written, shared by the two places one can be written: the draft
// row on the Pools table and the inline block in the new-experiment form.
//
// only the state and the submit live here. the two surfaces render genuinely
// differently — one is a table row that has to line up with existing columns,
// the other a card inside a form — and forcing one component to be both is how
// you get a component with a `variant` prop and two unrelated branches.

export type VariantDraft = { id: string; name: string; metadata: string };

const seed = (): VariantDraft[] => [
  { id: crypto.randomUUID(), name: "control", metadata: "" },
  { id: crypto.randomUUID(), name: "variant-a", metadata: "" },
];

export type PoolDraftIssue = "name" | "variant-count" | "variant-name" | "metadata";

export function usePoolDraft() {
  const [name, setName] = useState("");
  const [variants, setVariants] = useState<VariantDraft[]>(seed);
  const [submitting, setSubmitting] = useState(false);

  const reset = useCallback(() => {
    setName("");
    setVariants(seed());
  }, []);

  const addVariant = useCallback(() => {
    setVariants((v) => [...v, { id: crypto.randomUUID(), name: "", metadata: "" }]);
  }, []);

  const removeVariant = useCallback((id: string) => {
    setVariants((v) => (v.length <= 1 ? v : v.filter((x) => x.id !== id)));
  }, []);

  const updateVariant = useCallback(
    (id: string, field: "name" | "metadata", value: string) => {
      setVariants((v) =>
        v.map((x) => (x.id === id ? { ...x, [field]: value } : x)),
      );
    },
    [],
  );

  // a pool needs at least two variants to be an experiment: one arm is not a
  // choice, and the API will take it but nothing can ever be learned from it.
  const issue: PoolDraftIssue | null = useMemo(() => {
    if (!name.trim()) return "name";
    if (variants.length < 2) return "variant-count";
    if (variants.some((v) => !v.name.trim())) return "variant-name";
    for (const v of variants) {
      if (!v.metadata.trim()) continue;
      try {
        JSON.parse(v.metadata);
      } catch {
        return "metadata";
      }
    }
    return null;
  }, [name, variants]);

  const submit = useCallback(async (): Promise<Pool> => {
    setSubmitting(true);
    try {
      return await poolsApi.create({
        name: name.trim(),
        arms: variants.map((v) => ({
          name: v.name.trim(),
          metadata: v.metadata.trim() ? JSON.parse(v.metadata) : undefined,
        })),
      });
    } finally {
      setSubmitting(false);
    }
  }, [name, variants]);

  return {
    name,
    setName,
    variants,
    addVariant,
    removeVariant,
    updateVariant,
    issue,
    ready: issue === null,
    submitting,
    submit,
    reset,
  };
}

export const POOL_DRAFT_MESSAGE: Record<PoolDraftIssue, string> = {
  name: "Give the pool a name.",
  "variant-count": "A pool needs at least two variants — one is not a choice.",
  "variant-name": "Every variant needs a name.",
  metadata: "One of the variants has metadata that isn't valid JSON.",
};

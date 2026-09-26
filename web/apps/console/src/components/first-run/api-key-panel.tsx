"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, Key, Loader2 } from "lucide-react";
import { useToast } from "@qbrix/ui/components/toast";
import { auth } from "@/lib/api/auth";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/context";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { docsUrl } from "@/config/routes";

// board `APP · First run · empty console` / Your key.
//
// the board draws an existing key masked, which the api cannot serve: the
// plaintext is returned only by create and the list response carries no key
// field at all. a fresh tenant also has none, so the panel mints one and shows
// it once — which is the same contract Settings → API keys states.

const KEY_PLACEHOLDER = "optiq_…";

function snippetFor(apiKey: string): string {
  return `pip install qbrix

from qbrix import Qbrix

client = Qbrix(api_key="${apiKey}")

pool = client.pool.create(
    name="homepage-cta",
    arms=[{"name": "blue"}, {"name": "green"}],
)
exp = client.experiment.create(
    name="cta-test",
    pool_id=pool.id,
    policy="BetaTSPolicy",
)

r = client.agent.select(
    experiment_id=exp.id, context={"id": "u-1"}
)
client.agent.feedback(
    request_id=r.request_id, reward=1.0
)`;
}

export function ApiKeyPanel() {
  const toast = useToast();
  const toastApiError = useApiErrorToast();
  const queryClient = useQueryClient();
  const { user, refresh } = useAuth();

  // the plaintext lives in component state, so a reload loses it and there is
  // no endpoint that could give it back. say that, rather than silently
  // offering to mint a second key against the free tier's allowance of two.
  const existingKeys = user?.usage?.api_keys ?? 0;

  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const createMutation = useMutation({
    mutationFn: () => auth.createApiKey({ name: "First key" }),
    onSuccess: (result) => {
      setSecret(result.key);
      queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.all });
      void refresh();
    },
    onError: (err) => toastApiError(err, "Failed to create API key"),
  });

  async function copyKey() {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast.error("Couldn't copy — select the key and copy it manually.");
    }
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-[12px] border border-border-subtle bg-bg-raised">
      <div className="flex items-center justify-between gap-4 border-b border-border-subtle px-[18px] py-3.5">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.086em] text-text-faint">
          Your API key
        </span>
        {secret && (
          <button
            type="button"
            onClick={copyKey}
            className="font-mono text-[10.5px] uppercase tracking-[0.086em] text-text-dim transition-colors hover:text-text-primary"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>

      <div className="flex flex-col gap-2.5 px-[18px] py-4">
        {secret ? (
          <>
            <div className="flex items-center gap-2.5 rounded-lg border border-border-subtle bg-bg px-3 py-2.5">
              <Key size={14} className="shrink-0 text-text-faint" />
              <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-accent">
                {secret}
              </span>
            </div>
            <p className="text-[12.5px] leading-[1.5] text-text-faint">
              Shown once and stored as a hash — copy it now. You can issue
              another in Settings → API keys.
            </p>
          </>
        ) : (
          <>
            <p className="text-[13px] leading-[1.5] text-text-dim">
              {existingKeys > 0
                ? `This workspace already has ${existingKeys} ${existingKeys === 1 ? "key" : "keys"}. A key is shown once at creation and cannot be recovered — issue another here, or manage them in Settings.`
                : "You don't have a key yet. One call needs one — it is shown once and cannot be recovered afterwards."}
            </p>
            <button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
              className="flex h-9 items-center justify-center gap-2 self-start rounded-lg bg-accent px-4 text-[13.5px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Check size={14} />
              )}
              {existingKeys > 0 ? "Create another key" : "Create an API key"}
            </button>
          </>
        )}
      </div>

      <pre className="max-h-[252px] overflow-auto border-t border-border-subtle bg-bg px-[18px] py-4 font-mono text-[12px] leading-[1.7] text-text-secondary">
        {snippetFor(secret ?? KEY_PLACEHOLDER)}
      </pre>

      <a
        href={docsUrl("getting-started")}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-2 border-t border-border-subtle px-[18px] py-3.5 text-[13px] text-text-dim transition-colors hover:text-text-primary"
      >
        <BookOpen size={14} className="text-text-faint" />
        Full quickstart · Python, TypeScript, REST
      </a>
    </div>
  );
}

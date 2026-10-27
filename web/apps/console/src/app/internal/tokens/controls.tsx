"use client";

import { useState } from "react";
import { useToast } from "@qbrix/ui/components/toast";
import { Button, type ButtonVariant } from "@qbrix/ui/next/button";
import { Dialog } from "@qbrix/ui/next/dialog";
import { MonoField, TextArea, TextField } from "@qbrix/ui/next/field";
import { HoverCard } from "@qbrix/ui/next/hover-card";
import { Menu } from "@qbrix/ui/next/menu";
import { Picker } from "@qbrix/ui/next/picker";
import { Segmented } from "@qbrix/ui/next/segmented";
import { ActionBar, Sheet } from "@qbrix/ui/next/sheet";

const VARIANTS: [ButtonVariant, string][] = [
  ["primary", "Create draft"],
  ["secondary", "Keep paused"],
  ["quiet", "Cancel"],
  ["danger", "Delete draft"],
];

const METRICS = [
  { value: "checkout_completed", label: "checkout_completed", hint: "completed or not · 1 day" },
  { value: "order_value", label: "order_value", hint: "amount · 7 days" },
  { value: "search_clicked", label: "search_clicked", hint: "completed or not · 1 hour" },
];

const RANGES = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "cycle", label: "Cycle" },
] as const;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="n-meta text-n-text-3">{label}</span>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}

export function Controls() {
  const toast = useToast();
  const [metric, setMetric] = useState<string | null>(null);
  const [range, setRange] = useState<(typeof RANGES)[number]["value"]>("cycle");
  const [dialog, setDialog] = useState(false);
  const [sheet, setSheet] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      {(["md", "sm", "lg"] as const).map((size) => (
        <Row key={size} label={`buttons · ${size}`}>
          {VARIANTS.map(([variant, text]) => (
            <Button key={variant} variant={variant} size={size}>
              {text}
            </Button>
          ))}
        </Row>
      ))}
      <Row label="pending, and canEdit={false} (renders nothing after this label)">
        <Button disabled>Applying…</Button>
        <Button canEdit={false}>Launch</Button>
      </Row>

      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Name" defaultValue="Checkout headline" hint="Shown in the loops list and in every change." />
        <TextField label="Key" defaultValue="checkout headline" error="Keys are lowercase, with no spaces." />
        <TextArea
          label="Purpose"
          defaultValue="Help mobile visitors finish checkout. The headline above the pay button."
        />
        <MonoField multiline label="Config" defaultValue={'{ "cta": "Start annual, save 20%" }'} rows={2} />
        <MonoField label="Option key" defaultValue="annual_first" />
        <Picker
          label="Metric"
          value={metric}
          options={METRICS}
          onChange={setMetric}
          placeholder="Pick a metric"
          hint="pick a metric, or create one"
          create={{ label: "Create metric", onSelect: () => toast.info("Creating a metric opens beside the list.") }}
        />
      </div>

      <Row label="segmented, menu, hover card">
        <Segmented label="Range" value={range} options={[...RANGES]} onChange={setRange} />
        <Menu
          items={[
            { label: "Pin", onSelect: () => toast.success("Pinned.") },
            {
              label: "Delete draft",
              consequence: "Calls get the fallback until it's created again",
              tone: "danger",
              onSelect: () => toast.info("Deleted."),
            },
            { label: "Hidden for viewers", canEdit: false, onSelect: () => {} },
          ]}
        />
        <HoverCard
          trigger={
            <a href="https://github.com" className="n-body text-n-text-1 underline decoration-dotted underline-offset-2">
              #491
            </a>
          }
        >
          <span className="n-body font-medium text-n-text-1">Track checkout on the new payment sheet</span>
          <span className="n-meta text-n-text-2">acme/shop #491 · merged by Ada · 4 Oct</span>
          <span className="n-meta text-n-text-3">
            Also linked to version 3 of checkout_completed and to Checkout headline&apos;s history.
          </span>
        </HoverCard>
      </Row>

      <Row label="overlays">
        <Button variant="secondary" onClick={() => setDialog(true)}>
          Open dialog
        </Button>
        <Button variant="secondary" onClick={() => setSheet(true)}>
          Open sheet
        </Button>
      </Row>

      <Row label="toasts, through useToast()">
        <Button variant="secondary" onClick={() => toast.success("Loop launched.")}>
          Success
        </Button>
        <Button
          variant="secondary"
          onClick={() =>
            toast.errorRich({
              title: "Couldn't apply the change",
              message: "The loop changed since you opened it.",
              hint: "Reload to see the latest version.",
              action: { label: "Reload", onClick: () => {} },
            })
          }
        >
          Error
        </Button>
        <Button variant="secondary" onClick={() => toast.info("Copied the link.")}>
          Info
        </Button>
      </Row>

      <Row label="action bar (fixed to the bottom on a phone)">
        <ActionBar>
          <Button size="lg">Approve and start cycle 3</Button>
          <Button size="lg" variant="secondary">
            Ask for changes
          </Button>
          <Button size="lg" variant="secondary">
            Decline
          </Button>
        </ActionBar>
      </Row>

      <Dialog
        open={dialog}
        onClose={() => setDialog(false)}
        title="Resume Checkout headline?"
        footer={
          <>
            <Button variant="quiet" onClick={() => setDialog(false)}>
              Keep paused
            </Button>
            <Button onClick={() => setDialog(false)}>Resume</Button>
          </>
        }
      >
        <p>Traffic returns to the split qbrix learned before the pause. The current cycle continues.</p>
        <TextField label="Note, optional" placeholder="Why now" />
      </Dialog>

      <Sheet
        open={sheet}
        onClose={() => setSheet(false)}
        title="Decline adding Annual first?"
        actions={
          <>
            <Button size="lg" variant="secondary" onClick={() => setSheet(false)}>
              Cancel
            </Button>
            <Button size="lg" onClick={() => setSheet(false)}>
              Decline
            </Button>
          </>
        }
      >
        <TextArea label="Reason, optional" rows={4} />
        <p>Claude Code reads declined changes and their reasons before proposing again.</p>
      </Sheet>
    </div>
  );
}

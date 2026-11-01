"use client";

import { useState } from "react";
import { Rocket } from "lucide-react";
import { Button } from "@qbrix/ui/next/button";
import { ObjectPage, Property, RailSection, type ObjectTab } from "@qbrix/ui/next/object-page";
import { Consequence, Staged, StagedPreview, StagedTag } from "@qbrix/ui/next/staged";
import { StagedBar, type StagedChange } from "@qbrix/ui/next/staged-bar";
import { Wire } from "@qbrix/ui/next/wire";

const ONE: StagedChange[] = [
  {
    summary: "Add Free returns, 60 days",
    consequence: "Adding Free returns, 60 days starts cycle 3, which learns from scratch. Cycle 2 stays in history.",
  },
];

const TWO: StagedChange[] = [
  { summary: "Add Free returns, 60 days", consequence: "starts cycle 3" },
  { summary: "Narrow to mobile", consequence: "desktop gets Fewer returns" },
];

const THREE: StagedChange[] = [...TWO, { summary: "Roll out to 50%", consequence: "half of mobile gets Fewer returns" }];

const TABS: ObjectTab[] = [
  { key: "overview", label: "Overview", href: "#overview" },
  { key: "brief", label: "Brief", href: "#brief" },
  { key: "delivery", label: "Delivery", href: "#delivery" },
];

const noop = () => undefined;

function Fixture({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="n-meta text-n-text-3">{label}</span>
      {children}
    </div>
  );
}

function Bar({ changes, applying, canEdit }: { changes: StagedChange[]; applying?: boolean; canEdit?: boolean }) {
  return (
    <StagedBar changes={changes} onReview={noop} onDiscard={noop} onApply={noop} applying={applying} canEdit={canEdit} />
  );
}

export function StagedAndWire() {
  const [staged, setStaged] = useState(TWO);

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap gap-8">
        <Fixture label="Wire, a metric reported per decision">
          <Wire
            loopKey="checkout-headline"
            metricKind="outcome"
            className="w-[252px]"
            docs={<span className="n-meta text-n-text-3">The docs link goes here</span>}
          />
        </Fixture>
        <Fixture label="Wire, a metric reported as an event">
          <Wire loopKey="checkout-headline" metricKind="track" eventName="checkout_completed" className="w-[252px]" />
        </Fixture>
        <Fixture label="Wire, a long key">
          <Wire loopKey="checkout-headline-for-returning-mobile-visitors" metricKind="outcome" className="w-[252px]" />
        </Fixture>
      </div>

      <Fixture label="One change">
        <Bar changes={ONE} />
      </Fixture>
      <Fixture label="Two changes">
        <Bar changes={TWO} />
      </Fixture>
      <Fixture label="Three changes, wrapping before it hides a consequence">
        <Bar changes={THREE} />
      </Fixture>
      <Fixture label="Applying">
        <Bar changes={TWO} applying />
      </Fixture>
      <Fixture label="No changes: nothing renders">
        <div className="rounded-n-control border border-dashed border-n-line p-2">
          <Bar changes={[]} />
        </div>
      </Fixture>
      <Fixture label="A viewer: nothing renders">
        <div className="rounded-n-control border border-dashed border-n-line p-2">
          <Bar changes={TWO} canEdit={false} />
        </div>
      </Fixture>

      <Fixture label="On a page, above the tabs; Discard clears it">
        <div className="overflow-hidden rounded-n-panel border border-n-line">
          <ObjectPage
            crumbs={[{ label: "Loops", href: "#" }, { label: "Checkout headline" }]}
            tabs={TABS}
            activeTab="delivery"
            staged={
              <StagedBar changes={staged} onReview={noop} onDiscard={() => setStaged([])} onApply={() => setStaged([])} />
            }
            rail={
              <RailSection title="Properties">
                <Property label="State" value="Live" state="ok" />
              </RailSection>
            }
          >
            <div className="flex flex-col gap-4">
              <Staged label="Audience" note="Was: everyone. About 62% of checkout traffic is mobile.">
                <p className="n-support text-n-text-1">Visitors where device is mobile</p>
              </Staged>
              <StagedPreview>
                When both apply: cycle 3 starts with four options, for mobile visitors only. Desktop visitors get Fewer returns
                from then on.
              </StagedPreview>
            </div>
          </ObjectPage>
        </div>
      </Fixture>

      <Fixture label="A staged row in a table">
        <div className="flex items-center justify-between rounded-n-panel bg-n-fill-1 p-3">
          <span className="n-body text-n-text-1">Free returns, 60 days</span>
          <StagedTag />
        </div>
      </Fixture>

      <Fixture label="Launching a draft">
        <div className="rounded-n-panel border border-n-line bg-n-surface p-4">
          <Consequence
            title="Launching starts cycle 1 for mobile visitors."
            action={
              <Button>
                <Rocket size={13} />
                Launch
              </Button>
            }
          >
            Each option starts near a third of visitors and moves as qbrix learns. You can pause at any time; desktop visitors
            keep getting Fewer returns.
          </Consequence>
        </div>
      </Fixture>
    </div>
  );
}

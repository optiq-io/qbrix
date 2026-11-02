import { AskYourAgent, Code } from "@qbrix/ui/next/empty";
import { RailSection } from "@qbrix/ui/next/object-page";
import { wireCalls } from "@qbrix/ui/next/wire";
import { START_LOOP } from "@/lib/loop/new-loop";

function Step({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <h3 className="n-body font-medium text-n-text-1">{title}</h3>
      <p className="n-meta text-n-text-2">{children}</p>
    </div>
  );
}

export function AfterCreate({ loopKey }: { loopKey: string }) {
  return (
    <>
      <RailSection title="After you create it">
        <Step title="1  It's a draft">Calls to select already work and get the fallback, so wiring it is safe.</Step>
        <Step title="2  Wire it">Send the decision and its outcome:</Step>
        <Code>{wireCalls({ loopKey: loopKey || "your-loop", metricKind: "outcome" }).join("\n")}</Code>
        <Step title="3  Launch">Starts cycle 1 at an even split.</Step>
      </RailSection>
      <div className="mt-auto flex flex-col gap-2">
        <AskYourAgent label="Or ask your agent to set it up" prompts={[START_LOOP]} />
        <p className="n-meta text-n-text-3">
          It finds the place in your code and drafts the loop. Nothing changes for your users until it launches.
        </p>
      </div>
    </>
  );
}

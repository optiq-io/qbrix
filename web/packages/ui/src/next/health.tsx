import { Property, RailSection } from "./object-page";
import type { State } from "./state";

export type Signal = { label: string; value: React.ReactNode; state?: State };

export function Health({ signals, title = "Health", className }: { signals: Signal[]; title?: string; className?: string }) {
  return (
    <RailSection title={title} className={className}>
      {signals.map((signal) => (
        <Property key={signal.label} {...signal} />
      ))}
    </RailSection>
  );
}

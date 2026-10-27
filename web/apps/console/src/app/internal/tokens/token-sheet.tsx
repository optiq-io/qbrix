"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme, type Theme } from "@qbrix/ui/lib/theme";
import { NextRoot } from "@qbrix/ui/next/root";
import { Controls } from "./controls";

const NEUTRALS = [
  ["bg", "bg-n-bg", "the page behind panels"],
  ["surface", "bg-n-surface", "panels, the main column"],
  ["fill-1", "bg-n-fill-1", "selected row, hover, the staged bar"],
  ["fill-2", "bg-n-fill-2", "chips, filters, secondary controls"],
  ["line", "bg-n-line", "dividers between regions, panel and control borders"],
  ["line-2", "bg-n-line-2", "rows inside a list or table"],
  ["text-1", "bg-n-text-1", "primary text"],
  ["text-2", "bg-n-text-2", "supporting text"],
  ["text-3", "bg-n-text-3", "meta, labels, axes"],
  ["ink", "bg-n-ink", "things, figures, the leading option, primary buttons"],
  ["on-ink", "bg-n-on-ink", "text on ink"],
] as const;

const STATES = [
  ["ok", "Healthy", "bg-n-ok-bg text-n-ok-fg", "bg-n-ok-fg", "bg-n-ok-bg"],
  ["part", "Needs attention", "bg-n-part-bg text-n-part-fg", "bg-n-part-fg", "bg-n-part-bg"],
  ["no", "Broken", "bg-n-no-bg text-n-no-fg", "bg-n-no-fg", "bg-n-no-bg"],
  ["new", "Waits on you", "bg-n-new-bg text-n-new-fg", "bg-n-new-fg", "bg-n-new-bg"],
] as const;

const RAMP = [
  ["ink", "bg-n-ink", "leading option"],
  ["viz-2", "bg-n-viz-2", "second option, past bars"],
  ["viz-3", "bg-n-viz-3", "third option, others"],
  ["viz-track", "bg-n-viz-track", "empty share, chart track"],
] as const;

const TYPE = [
  ["n-lead", "28 · lead", "Checkout headline is healthy and learning."],
  ["n-support", "15 · lead support", "Up from 41% on 4 October, when Ada narrowed the audience."],
  ["n-body", "13 · body and titles", "How it learned · Ada narrowed the audience to mobile visitors"],
  ["n-meta", "12 · meta", "38 decisions a second · learned 40 seconds ago · 4 Oct"],
  ["n-label", "11 · label", "Share now     Health     Waiting on you"],
  ["n-mono", "12 · mono", 'checkout_completed   req_8f1d   select("checkout-headline", ctx)'],
] as const;

const SPACING = [
  ["1", "w-1", "4", "icon to label, inside pills"],
  ["2", "w-2", "8", "chip padding, between chips, list cells"],
  ["3", "w-3", "12", "control padding, row padding"],
  ["4", "w-4", "16", "between groups in the rail"],
  ["6", "w-6", "24", "panel padding, page gutter"],
  ["8", "w-8", "32", "between sections of a page"],
  ["12", "w-12", "48", "lead to the evidence below it"],
] as const;

const RADII = [
  ["rounded-n-chip", "4 · chips, pills, keys"],
  ["rounded-n-control", "6 · buttons, inputs"],
  ["rounded-n-panel", "8 · panels, cards, the app frame"],
] as const;

const THEMES: Theme[] = ["system", "light", "dark"];

function hex(rgb: string) {
  const parts = rgb.match(/\d+(\.\d+)?/g);
  if (!parts || parts.length < 3) return rgb;
  return (
    "#" +
    parts
      .slice(0, 3)
      .map((p) => Math.round(Number(p)).toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()
  );
}

function useSchemeVersion(theme: Theme) {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const bump = () => setVersion((v) => v + 1);
    media.addEventListener("change", bump);
    bump();
    return () => media.removeEventListener("change", bump);
  }, [theme]);
  return version;
}

function Swatch({ name, className, note, version }: { name: string; className: string; note: string; version: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [value, setValue] = useState("");
  useEffect(() => {
    if (ref.current) setValue(hex(getComputedStyle(ref.current).backgroundColor));
  }, [version]);
  return (
    <div className="flex items-center gap-3 py-2">
      <div ref={ref} className={`h-8 w-8 shrink-0 rounded-n-chip border border-n-line ${className}`} />
      <span className="n-mono w-24 text-n-text-1">{name}</span>
      <span className="n-mono w-20 text-n-text-3">{value}</span>
      <span className="n-meta text-n-text-2">{note}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-n-panel border border-n-line bg-n-surface p-6">
      <h2 className="n-body mb-4 font-medium text-n-text-1">{title}</h2>
      {children}
    </section>
  );
}

export function TokenSheet() {
  const { theme, setTheme } = useTheme();
  const version = useSchemeVersion(theme);

  return (
    <NextRoot>
      <div className="mx-auto flex max-w-4xl flex-col gap-8 px-6 py-12">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="n-lead">Tokens</h1>
            <p className="n-support text-n-text-2">The next console&apos;s roles, type and shape, in the current theme.</p>
          </div>
          <div className="flex gap-1 rounded-n-control bg-n-fill-2 p-1">
            {THEMES.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setTheme(option)}
                className={`n-body rounded-n-chip px-3 py-1 capitalize ${
                  theme === option ? "bg-n-surface text-n-text-1" : "text-n-text-2"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </header>

        <Section title="Neutral roles">
          <div className="divide-y divide-n-line-2">
            {NEUTRALS.map(([name, className, note]) => (
              <Swatch key={name} name={name} className={className} note={note} version={version} />
            ))}
          </div>
        </Section>

        <Section title="States">
          <div className="mb-4 flex flex-wrap gap-2">
            {STATES.map(([name, label, pill]) => (
              <span key={name} className={`n-label rounded-n-chip px-2 py-1 ${pill}`}>
                {label}
              </span>
            ))}
          </div>
          <div className="divide-y divide-n-line-2">
            {STATES.flatMap(([name, , , fg, bg]) => [
              <Swatch key={`${name}-fg`} name={`${name}-fg`} className={fg} note="text and marks" version={version} />,
              <Swatch key={`${name}-bg`} name={`${name}-bg`} className={bg} note="pill ground" version={version} />,
            ])}
          </div>
        </Section>

        <Section title="Chart ramp">
          <div className="mb-4 flex h-6 overflow-hidden rounded-n-chip">
            <div className="w-[46%] bg-n-ink" />
            <div className="w-[27%] bg-n-viz-2" />
            <div className="w-[18%] bg-n-viz-3" />
            <div className="w-[9%] bg-n-viz-track" />
          </div>
          <div className="divide-y divide-n-line-2">
            {RAMP.map(([name, className, note]) => (
              <Swatch key={name} name={name} className={className} note={note} version={version} />
            ))}
          </div>
        </Section>

        <Section title="Controls">
          <Controls />
        </Section>

        <Section title="Type">
          <div className="flex flex-col gap-6">
            {TYPE.map(([className, label, sample]) => (
              <div key={className}>
                <div className="n-meta mb-1 text-n-text-3">
                  <span className="font-n-mono">{className}</span> · {label}
                </div>
                <div className={className}>{sample}</div>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Spacing">
          <div className="flex flex-col gap-2">
            {SPACING.map(([step, width, px, note]) => (
              <div key={step} className="flex items-center gap-3">
                <span className="n-mono w-8 text-n-text-3">{step}</span>
                <span className="w-12">
                  <span className={`block h-3 bg-n-ink ${width}`} />
                </span>
                <span className="n-meta w-8 tabular-nums text-n-text-1">{px}</span>
                <span className="n-meta text-n-text-2">{note}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Radii and lines">
          <div className="mb-6 flex gap-6">
            {RADII.map(([className, note]) => (
              <div key={className} className="flex flex-col gap-2">
                <div className={`h-16 w-24 border border-n-line bg-n-fill-1 ${className}`} />
                <span className="n-meta text-n-text-2">{note}</span>
              </div>
            ))}
          </div>
          <div className="n-meta flex flex-col gap-3 text-n-text-2">
            <div className="border-t border-n-line pt-2">line · dividers between regions, panel and control borders</div>
            <div className="border-t border-n-line-2 pt-2">line-2 · rows inside a list or table</div>
          </div>
        </Section>
      </div>
    </NextRoot>
  );
}

export function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="n-body font-semibold text-n-text-1">{title}</h2>
        {note && <span className="n-meta text-n-text-3">{note}</span>}
      </div>
      {children}
    </section>
  );
}

export function Fact({ label, value, quiet = false }: { label: string; value: string; quiet?: boolean }) {
  return (
    <span className="n-meta inline-flex gap-1">
      <span className="text-n-text-3">{label}</span>
      <span className={quiet ? "text-n-text-3" : "text-n-text-1"}>{value}</span>
    </span>
  );
}

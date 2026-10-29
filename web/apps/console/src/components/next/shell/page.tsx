export function NextPage({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col gap-6 px-8 py-8">
      <h1 className="n-lead">{title}</h1>
      {children}
    </div>
  );
}

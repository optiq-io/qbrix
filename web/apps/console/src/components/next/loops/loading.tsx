import { ObjectPage } from "@qbrix/ui/next/object-page";
import { SkeletonHeader, SkeletonList, SkeletonRail } from "@qbrix/ui/next/skeleton";

const COLUMNS = [
  { lines: [160, 200] },
  { width: 150, lines: [120] },
  { width: 140, lines: [90, 60] },
  { width: 110, lines: [70] },
];

export function LoopsLoading() {
  return (
    <ObjectPage crumbs={[{ label: "Loops" }]} rail={<SkeletonRail groups={[3]} />}>
      <div aria-busy className="flex flex-col gap-10">
        <SkeletonHeader />
        <SkeletonList columns={COLUMNS} rows={4} />
      </div>
    </ObjectPage>
  );
}

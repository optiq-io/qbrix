import { ObjectPage } from "@qbrix/ui/next/object-page";
import { SkeletonHeader, SkeletonList, SkeletonRail } from "@qbrix/ui/next/skeleton";

const COLUMNS = [{ lines: [140, 260, 160] }, { width: 252, lines: [120] }];

export function MetricsLoading() {
  return (
    <ObjectPage crumbs={[{ label: "Metrics" }]} rail={<SkeletonRail groups={[1, 5]} />}>
      <div aria-busy className="flex flex-col gap-10">
        <SkeletonHeader item={false} facts={3} />
        <SkeletonList columns={COLUMNS} rows={4} />
      </div>
    </ObjectPage>
  );
}

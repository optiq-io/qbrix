import { ObjectPage } from "@qbrix/ui/next/object-page";
import { SkeletonBlock, SkeletonRail, SkeletonText } from "@qbrix/ui/next/skeleton";

export const PANEL_RAIL = "w-[400px] bg-n-surface";

const ROWS = [
  [260, 200, 300],
  [200, 160, 240],
  [280, 180, 260],
  [240, 200, 300],
  [220, 160, 240],
];

export function ChangesLoading() {
  return (
    <ObjectPage crumbs={[{ label: "Changes" }]} rail={<SkeletonRail groups={[4, 1, 2]} />} railClassName={PANEL_RAIL}>
      <div aria-busy className="flex flex-col gap-5">
        <SkeletonText type="label" width={360} />
        <SkeletonBlock height={26} className="max-w-[560px]" />
        <div className="flex flex-col gap-0.5">
          <SkeletonText type="label" width={40} />
          {ROWS.map((lines, row) => (
            <div key={row} className="flex gap-3 px-3 py-2.5">
              <span className="size-5 shrink-0 rounded-full bg-n-fill-2" />
              <div className="flex flex-col gap-[3px]">
                <SkeletonText width={lines[0]} />
                <SkeletonText type="meta" width={lines[1]} />
                <SkeletonText type="meta" width={lines[2]} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </ObjectPage>
  );
}

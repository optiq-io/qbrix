import { ObjectPage } from "@qbrix/ui/next/object-page";
import { SkeletonBlock, SkeletonHeader, SkeletonRail, SkeletonText } from "@qbrix/ui/next/skeleton";
import { routes } from "@/config/routes";

export function LoopLoading() {
  return (
    <ObjectPage
      crumbs={[{ label: "Loops", href: routes.next.home }]}
      rail={<SkeletonRail groups={[5, 3, 4]} />}
    >
      <div aria-busy className="flex flex-col gap-8">
        <SkeletonHeader />
        <SkeletonBlock height={220} />
        <div aria-hidden className="flex flex-col gap-3">
          {[420, 360, 480, 300].map((width) => (
            <SkeletonText key={width} width={width} />
          ))}
        </div>
      </div>
    </ObjectPage>
  );
}

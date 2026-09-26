import { FileQuestion } from "lucide-react";
import { EmptyState } from "@qbrix/ui/components/empty-state";
import { routes } from "@/config/routes";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg">
      <EmptyState
        icon={
          <FileQuestion
            size={40}
            strokeWidth={1.25}
            className="text-text-faint"
          />
        }
        title="This page doesn't exist"
        description="The link may be out of date, or it points at something this deployment does not run."
        primaryAction={{
          label: "Back to home",
          href: routes.home,
          shape: "neutral",
        }}
      />
    </div>
  );
}

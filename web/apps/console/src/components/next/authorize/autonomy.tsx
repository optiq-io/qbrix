import type { ConnectionRequest } from "@/lib/api/types";

export function Autonomy({ request }: { request: ConnectionRequest }) {
  if (!request.applies_at_once) return null;
  return (
    <div className="n-meta rounded-n-panel border border-n-line px-4 py-3 text-n-text-1">
      Its changes apply at once, without asking you first.
    </div>
  );
}

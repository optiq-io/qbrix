import { cn } from "../lib/utils";
import { Toaster } from "./toast";

/** the next console's scope: tokens, theme, and its own toaster. place it inside <body>,
    never on <html> */
export function NextRoot({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div data-console="next" className={cn("min-h-screen bg-n-bg text-n-text-1", className)}>
      {children}
      <Toaster />
    </div>
  );
}

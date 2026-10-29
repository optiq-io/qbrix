import { notFound } from "next/navigation";
import { NextShell } from "@/components/next/shell/shell";

export default function NextLayout({ children }: { children: React.ReactNode }) {
  if (process.env.NEXT_PUBLIC_CONSOLE_NEXT !== "true") notFound();
  return <NextShell>{children}</NextShell>;
}

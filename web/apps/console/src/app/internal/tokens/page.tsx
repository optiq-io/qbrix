import { notFound } from "next/navigation";
import { TokenSheet } from "./token-sheet";

export default function TokensPage() {
  if (process.env.NEXT_PUBLIC_CONSOLE_NEXT !== "true") notFound();
  return <TokenSheet />;
}

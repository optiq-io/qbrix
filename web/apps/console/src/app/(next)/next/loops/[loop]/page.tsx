import { LoopPage } from "@/components/next/loop/loop-page";

export default async function Page({ params }: { params: Promise<{ loop: string }> }) {
  const { loop } = await params;
  return <LoopPage loopKey={decodeURIComponent(loop)} />;
}

import Link from "next/link";
import { buttonClass } from "@qbrix/ui/next/button";
import { NextPage } from "@/components/next/shell/page";
import { routes } from "@/config/routes";

export default function NextNotFound() {
  return (
    <NextPage title="There's nothing at this link">
      <p className="n-support text-n-text-2">
        The address may be mistyped, or what it pointed to isn&apos;t in this workspace.
      </p>
      <Link href={routes.next.home} className={buttonClass("secondary", "md", "self-start")}>
        Go to loops
      </Link>
    </NextPage>
  );
}

"use client";

import Link from "next/link";
import { QbrixBrick } from "@qbrix/ui/components/logo";
import { cn } from "@qbrix/ui/lib/utils";
import { useDeployment } from "@/lib/deployment";

// boards `APP · Sign in` (1440 = form side 780 + showcase 660) and
// `APP · Sign in @ 390`. rule F puts every auth surface at full responsive:
// each one is reached from an email, and email is read on a phone.
//
// grid rather than two flex columns because the stacking order differs from
// the desktop order — at 390 the showcase sits *between* the form and the
// footer, while at lg the footer belongs under the form and the showcase
// spans the full height beside it.

// privacy and terms are qbrix cloud's own, and a self-hosted instance is not
// party to them. the docs describe the software either way.
const CLOUD_LINKS = [
  { label: "Privacy", href: "https://qbrix.io/privacy" },
  { label: "Terms", href: "https://qbrix.io/terms" },
];

const DOCS_LINK = { label: "Docs", href: "https://qbrix.io/docs" };

export function AuthShell({
  showcase,
  children,
}: {
  showcase?: React.ReactNode;
  children: React.ReactNode;
}) {
  const { isCloud } = useDeployment();
  const footerLinks = isCloud ? [...CLOUD_LINKS, DOCS_LINK] : [DOCS_LINK];

  return (
    <div
      className={cn(
        "grid min-h-screen grid-cols-1 bg-bg",
        showcase
          ? "lg:grid-cols-[1fr_560px] lg:grid-rows-[1fr_auto] xl:grid-cols-[1fr_660px]"
          : "lg:grid-rows-[1fr_auto]",
      )}
    >
      <div
        className={cn(
          "flex flex-col items-center px-5 pt-10 md:px-10 lg:px-14 lg:pt-10 xl:px-20",
          // beside a showcase the column sits at the board's 80px inset; alone
          // on the page a transactional card belongs in the middle of it
          showcase && "lg:items-start",
        )}
      >
        <div
          className={cn(
            "flex w-full flex-1 flex-col",
            showcase ? "max-w-[380px]" : "max-w-[420px]",
          )}
        >
          <Link
            href="https://qbrix.io"
            className="flex items-center gap-2.5 transition-opacity hover:opacity-70"
          >
            <QbrixBrick size={22} />
            <span className="font-heading text-[15px] font-semibold text-text-primary">
              qbrix
            </span>
          </Link>
          <div className="flex flex-1 flex-col justify-center py-12">
            {children}
          </div>
        </div>
      </div>

      {showcase && (
        <div className="flex flex-col justify-center bg-bg-raised px-6 py-12 md:px-10 lg:row-span-2 lg:px-14 lg:py-16">
          {showcase}
        </div>
      )}

      <div
        className={cn(
          "flex justify-center px-5 pb-8 pt-10 md:px-10 lg:col-start-1 lg:row-start-2 lg:px-14 lg:pt-0 xl:px-20",
          showcase && "lg:justify-start",
        )}
      >
        <div
          className={cn(
            "flex w-full items-center gap-6",
            showcase ? "max-w-[380px]" : "max-w-[420px] justify-center",
          )}
        >
          {footerLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="text-[12.5px] text-text-faint transition-colors hover:text-text-dim"
            >
              {link.label}
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}

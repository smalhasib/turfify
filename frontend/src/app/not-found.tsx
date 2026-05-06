import Link from "next/link";

import { Header } from "@/components/ui/Header";

export default function NotFound() {
  return (
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-xl flex-col gap-md px-md py-3xl text-center">
        <p className="label-caps text-brand">404</p>
        <h1 className="stadium-display text-6xl uppercase text-ink">
          Off the pitch.
        </h1>
        <p className="text-base text-ink-soft">
          That page isn&apos;t in the squad list. Check the URL or head back
          home.
        </p>
        <div className="flex justify-center gap-sm pt-2xs">
          <Link
            href="/"
            className="inline-flex min-h-[44px] items-center rounded-sm bg-accent px-md py-2xs font-sans text-sm font-semibold uppercase tracking-wide text-[oklch(0.18_0.02_145)] hover:bg-accent-deep hover:text-[oklch(0.96_0.01_95)]"
          >
            Home
          </Link>
          <Link
            href="/book"
            className="inline-flex min-h-[44px] items-center rounded-sm border border-rule-strong px-md py-2xs font-sans text-sm font-semibold uppercase tracking-wide text-ink hover:bg-surface-2"
          >
            Book a slot
          </Link>
        </div>
      </main>
    </>
  );
}

"use client";

import { useEffect } from "react";

import { Header } from "@/components/ui/Header";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Phase 14: pipe to Sentry once DSN is wired.
    console.error("App-level error:", error);
  }, [error]);

  return (
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-xl flex-col gap-md px-md py-3xl text-center">
        <p className="label-caps text-[var(--color-danger)]">Something broke</p>
        <h1 className="stadium-display text-6xl uppercase text-ink">
          Match abandoned.
        </h1>
        <p className="text-base text-ink-soft">
          The app hit an error. Try again, or head home and re-attempt.
        </p>
        <div className="flex justify-center gap-sm pt-2xs">
          <button
            type="button"
            onClick={() => reset()}
            className="inline-flex min-h-[44px] items-center rounded-sm bg-accent px-md py-2xs font-sans text-sm font-semibold uppercase tracking-wide text-[oklch(0.18_0.02_145)] hover:bg-accent-deep hover:text-[oklch(0.96_0.01_95)]"
          >
            Retry
          </button>
        </div>
      </main>
    </>
  );
}

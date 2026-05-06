"use client";

import Link from "next/link";

import { useAuthHydrated, useAuthStore } from "@/lib/authStore";

export function Header() {
  const hydrated = useAuthHydrated();
  const user = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);

  const isAuthed = hydrated && Boolean(accessToken);

  return (
    <header className="sticky top-0 z-10 border-b border-rule/60 bg-bg/80 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-md">
        <Link
          href="/"
          className="wordmark text-2xl tracking-tight text-ink hover:text-brand"
          aria-label="Turfify home"
        >
          TURFIFY
        </Link>
        <nav className="flex items-center gap-xs">
          {isAuthed ? (
            <Link
              href="/me"
              className="rounded-xs px-xs py-2xs text-sm font-medium text-ink-soft hover:bg-surface-2 hover:text-ink"
            >
              {user?.name ?? user?.phone ?? "Account"}
            </Link>
          ) : (
            <Link
              href="/login"
              className="rounded-xs px-xs py-2xs text-sm font-medium text-ink-soft hover:bg-surface-2 hover:text-ink"
              data-testid="nav-signin"
            >
              Sign in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}

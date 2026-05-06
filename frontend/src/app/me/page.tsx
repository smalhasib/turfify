"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { logout } from "@/lib/auth";
import { type AuthUser, useAuthHydrated, useAuthStore } from "@/lib/authStore";
import { getApiClient } from "@/lib/api";

export default function MePage() {
  const router = useRouter();
  const hydrated = useAuthHydrated();
  const storedUser = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);
  const [user, setUser] = useState<AuthUser | null>(storedUser);
  const [loading, setLoading] = useState(!storedUser);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    if (storedUser) {
      setUser(storedUser);
      setLoading(false);
      return;
    }

    let cancelled = false;
    getApiClient()
      .get<AuthUser>("/me")
      .then(({ data }) => {
        if (cancelled) return;
        setUser(data);
        useAuthStore.getState().setUser(data);
      })
      .catch(() => {
        if (cancelled) return;
        router.replace("/login");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, accessToken, storedUser, router]);

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  if (loading) {
    return <p className="p-12 text-sm text-neutral-500">Loading…</p>;
  }
  if (!user) {
    return null;
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-6 py-12">
      <h1 className="text-3xl font-bold tracking-tight text-brand-700">Welcome</h1>
      <dl
        className="grid grid-cols-[8rem_1fr] gap-y-2 rounded border border-neutral-200 p-6 text-sm"
        data-testid="me-card"
      >
        <dt className="font-medium text-neutral-500">Phone</dt>
        <dd data-testid="me-phone">{user.phone}</dd>
        <dt className="font-medium text-neutral-500">Name</dt>
        <dd>{user.name ?? "—"}</dd>
        <dt className="font-medium text-neutral-500">Role</dt>
        <dd className="capitalize" data-testid="me-role">
          {user.role}
        </dd>
      </dl>
      <button
        type="button"
        onClick={onLogout}
        data-testid="logout"
        className="self-start rounded border border-neutral-300 px-4 py-2 text-sm font-medium hover:bg-neutral-100"
      >
        Sign out
      </button>
    </main>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Header } from "@/components/ui/Header";
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
    return (
      <>
        <Header />
        <main className="mx-auto max-w-2xl p-2xl text-sm text-ink-mute">Loading…</main>
      </>
    );
  }
  if (!user) {
    return null;
  }

  const roleLabel: Record<AuthUser["role"], string> = {
    customer: "Player",
    staff: "Staff",
    admin: "Admin",
  };

  return (
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-2xl flex-col gap-lg px-md py-2xl">
        <div className="flex flex-col gap-2xs">
          <p className="label-caps text-brand">Profile</p>
          <h1 className="stadium-display text-5xl uppercase text-ink">
            {user.name ? `Hey, ${user.name}.` : "Welcome."}
          </h1>
        </div>

        <dl
          className="grid gap-sm border-t border-rule pt-md sm:grid-cols-2"
          data-testid="me-card"
        >
          <Row label="Phone" value={user.phone} testid="me-phone" />
          <Row label="Role" value={roleLabel[user.role]} testid="me-role" />
          <Row label="Name" value={user.name ?? "—"} />
          <Row label="Email" value={user.email ?? "Not set"} />
        </dl>

        <div className="flex flex-wrap gap-sm pt-md">
          <Button variant="outline" onClick={onLogout} data-testid="logout">
            Sign out
          </Button>
        </div>
      </main>
    </>
  );
}

function Row({ label, value, testid }: { label: string; value: string; testid?: string }) {
  return (
    <div className="flex flex-col gap-3xs">
      <dt className="label-caps text-ink-soft">{label}</dt>
      <dd className="font-sans text-base text-ink" data-testid={testid}>
        {value}
      </dd>
    </div>
  );
}

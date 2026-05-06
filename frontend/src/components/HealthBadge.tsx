"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";
import { fetchHealth, type HealthCheckResponse } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ok"; data: HealthCheckResponse }
  | { kind: "error"; message: string };

export function HealthBadge() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((data) => {
        if (!cancelled) setState({ kind: "ok", data });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "unknown error";
          setState({ kind: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const dotClass = cn(
    "inline-block h-2 w-2 rounded-full",
    state.kind === "ok" && "bg-success",
    state.kind === "error" && "bg-[var(--color-danger)]",
    state.kind === "loading" && "bg-ink-mute animate-pulse",
  );

  if (state.kind === "loading") {
    return (
      <p className="flex items-center gap-2xs text-sm text-ink-mute" data-testid="health-status">
        <span className={dotClass} aria-hidden />
        Checking…
      </p>
    );
  }
  if (state.kind === "error") {
    return (
      <p
        className="flex items-center gap-2xs text-sm text-[var(--color-danger)]"
        data-testid="health-status"
      >
        <span className={dotClass} aria-hidden />
        unreachable — {state.message}
      </p>
    );
  }
  return (
    <p
      className="flex items-center gap-2xs text-sm font-medium text-ink"
      data-testid="health-status"
    >
      <span className={dotClass} aria-hidden />
      {state.data.status} (v{state.data.checks.version})
    </p>
  );
}

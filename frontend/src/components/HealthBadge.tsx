"use client";

import { useEffect, useState } from "react";

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

  if (state.kind === "loading") {
    return <p className="text-sm text-neutral-500">Checking…</p>;
  }
  if (state.kind === "error") {
    return (
      <p className="text-sm text-red-600" data-testid="health-status">
        unreachable — {state.message}
      </p>
    );
  }
  return (
    <p className="text-sm font-medium text-brand-600" data-testid="health-status">
      {state.data.status} (v{state.data.checks.version})
    </p>
  );
}

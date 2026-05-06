import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HealthBadge } from "@/components/HealthBadge";

const mockFetch = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
});
afterEach(() => {
  vi.unstubAllGlobals();
  mockFetch.mockReset();
});

describe("HealthBadge", () => {
  it("renders ok status when API healthy", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        status: "ok",
        checks: { db: "ok", redis: "ok", version: "0.1.0" },
      }),
    });

    render(<HealthBadge />);

    await waitFor(() => {
      expect(screen.getByTestId("health-status")).toHaveTextContent("ok");
      expect(screen.getByTestId("health-status")).toHaveTextContent("0.1.0");
    });
  });

  it("renders error when API unreachable", async () => {
    mockFetch.mockRejectedValueOnce(new Error("fetch failed"));

    render(<HealthBadge />);

    await waitFor(() => {
      expect(screen.getByTestId("health-status")).toHaveTextContent("unreachable");
    });
  });
});

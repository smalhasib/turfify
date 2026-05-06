import { beforeEach, describe, expect, it } from "vitest";

import { type CartSlot, useCartStore } from "@/lib/cartStore";

function slot(startAt: string, price: number): CartSlot {
  return {
    startAt,
    endAt: startAt.replace("T13:", "T14:"),
    priceBdt: price,
    label: `Slot ${startAt}`,
  };
}

describe("useCartStore", () => {
  beforeEach(() => {
    useCartStore.getState().clear();
  });

  it("starts empty", () => {
    expect(useCartStore.getState().slots).toEqual([]);
    expect(useCartStore.getState().venueId).toBeNull();
    expect(useCartStore.getState().total()).toBe(0);
  });

  it("adds a slot via toggle", () => {
    useCartStore.getState().toggle(1, slot("2026-05-12T13:00:00Z", 1000));
    expect(useCartStore.getState().slots).toHaveLength(1);
    expect(useCartStore.getState().venueId).toBe(1);
  });

  it("removes a slot when toggled twice", () => {
    const s = slot("2026-05-12T13:00:00Z", 1000);
    useCartStore.getState().toggle(1, s);
    useCartStore.getState().toggle(1, s);
    expect(useCartStore.getState().slots).toEqual([]);
  });

  it("sorts slots chronologically when adding out of order", () => {
    useCartStore.getState().toggle(1, slot("2026-05-12T15:00:00Z", 1000));
    useCartStore.getState().toggle(1, slot("2026-05-12T13:00:00Z", 1000));
    useCartStore.getState().toggle(1, slot("2026-05-12T14:00:00Z", 1000));
    const starts = useCartStore.getState().slots.map((s) => s.startAt);
    expect(starts).toEqual([
      "2026-05-12T13:00:00Z",
      "2026-05-12T14:00:00Z",
      "2026-05-12T15:00:00Z",
    ]);
  });

  it("sums total across slots", () => {
    useCartStore.getState().toggle(1, slot("2026-05-12T13:00:00Z", 1000));
    useCartStore.getState().toggle(1, slot("2026-05-12T14:00:00Z", 1500));
    expect(useCartStore.getState().total()).toBe(2500);
  });

  it("starts fresh when toggling a slot from a different venue", () => {
    useCartStore.getState().toggle(1, slot("2026-05-12T13:00:00Z", 1000));
    useCartStore.getState().toggle(2, slot("2026-05-12T15:00:00Z", 1500));
    expect(useCartStore.getState().venueId).toBe(2);
    expect(useCartStore.getState().slots).toHaveLength(1);
    expect(useCartStore.getState().slots[0]!.priceBdt).toBe(1500);
  });

  it("remove() drops a single slot by startAt", () => {
    useCartStore.getState().toggle(1, slot("2026-05-12T13:00:00Z", 1000));
    useCartStore.getState().toggle(1, slot("2026-05-12T14:00:00Z", 1500));
    useCartStore.getState().remove("2026-05-12T13:00:00Z");
    expect(useCartStore.getState().slots).toHaveLength(1);
    expect(useCartStore.getState().slots[0]!.startAt).toBe("2026-05-12T14:00:00Z");
  });

  it("clear() resets everything", () => {
    useCartStore.getState().toggle(1, slot("2026-05-12T13:00:00Z", 1000));
    useCartStore.getState().clear();
    expect(useCartStore.getState().slots).toEqual([]);
    expect(useCartStore.getState().venueId).toBeNull();
  });
});

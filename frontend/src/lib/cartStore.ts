"use client";

import { create } from "zustand";

export type CartSlot = {
  startAt: string; // ISO UTC
  endAt: string;
  priceBdt: number;
  /** Local-tz pretty label cached at add time so reload survives without refetch. */
  label: string;
};

type CartState = {
  venueId: number | null;
  slots: CartSlot[];
  toggle: (venueId: number, slot: CartSlot) => void;
  remove: (startAt: string) => void;
  clear: () => void;
  total: () => number;
};

export const useCartStore = create<CartState>()((set, get) => ({
  venueId: null,
  slots: [],
  toggle: (venueId, slot) => {
    const state = get();
    if (state.venueId !== null && state.venueId !== venueId) {
      // Switching venues — start fresh.
      set({ venueId, slots: [slot] });
      return;
    }
    const exists = state.slots.find((s) => s.startAt === slot.startAt);
    if (exists) {
      set({ slots: state.slots.filter((s) => s.startAt !== slot.startAt) });
    } else {
      set({
        venueId,
        slots: [...state.slots, slot].sort((a, b) =>
          a.startAt < b.startAt ? -1 : 1,
        ),
      });
    }
  },
  remove: (startAt) =>
    set((state) => ({
      slots: state.slots.filter((s) => s.startAt !== startAt),
    })),
  clear: () => set({ venueId: null, slots: [] }),
  total: () => {
    const { slots } = get();
    return slots.reduce((acc, s) => acc + s.priceBdt, 0);
  },
}));

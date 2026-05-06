"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { createHold } from "@/lib/bookings";
import { type CartSlot, useCartStore } from "@/lib/cartStore";
import { formatPriceBdt } from "@/lib/calendar";
import { useAuthHydrated, useAuthStore } from "@/lib/authStore";

function HoldErrorBanner({ message }: { message: string }) {
  return (
    <p
      role="alert"
      data-testid="cart-error"
      className="rounded-xs border border-[var(--color-danger)] bg-bg px-sm py-xs text-sm text-[var(--color-danger)]"
    >
      {message}
    </p>
  );
}

function CartRow({ slot }: { slot: CartSlot }) {
  const remove = useCartStore((s) => s.remove);
  return (
    <li className="flex items-center justify-between gap-sm border-b border-rule/60 py-2xs last:border-0">
      <div className="flex flex-col">
        <span className="text-sm font-medium text-ink">{slot.label}</span>
        <span className="text-xs text-ink-mute">{formatPriceBdt(slot.priceBdt)}</span>
      </div>
      <button
        type="button"
        onClick={() => remove(slot.startAt)}
        className="text-xs uppercase tracking-wide text-ink-soft hover:text-[var(--color-danger)]"
      >
        Remove
      </button>
    </li>
  );
}

export function CartPanel() {
  const router = useRouter();
  const hydrated = useAuthHydrated();
  const accessToken = useAuthStore((s) => s.accessToken);
  const venueId = useCartStore((s) => s.venueId);
  const slots = useCartStore((s) => s.slots);
  const total = useCartStore((s) => s.total());
  const clear = useCartStore((s) => s.clear);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (slots.length === 0) {
    return (
      <aside
        className="rounded-md border border-rule bg-surface p-md"
        data-testid="cart-empty"
      >
        <p className="label-caps text-ink-soft">Cart</p>
        <p className="mt-2xs text-sm text-ink-mute">
          Pick slots from the grid to start a booking.
        </p>
      </aside>
    );
  }

  async function onContinue() {
    if (!hydrated) return;
    if (!accessToken) {
      router.push("/login");
      return;
    }
    if (venueId === null) return;

    setBusy(true);
    setError(null);
    try {
      const result = await createHold({
        venue_id: venueId,
        slots: slots.map((s) => ({ start_at: s.startAt })),
      });
      clear();
      router.push(`/booking/${result.booking_id}`);
    } catch (err: unknown) {
      type ErrLike = { response?: { data?: { detail?: string } }; message?: string };
      const e = err as ErrLike;
      const detail = e?.response?.data?.detail ?? e?.message ?? "Hold failed";
      setError(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside
      className="flex flex-col gap-sm rounded-md border border-rule bg-surface p-md"
      data-testid="cart-panel"
    >
      <div className="flex items-baseline justify-between">
        <p className="label-caps text-brand">Cart</p>
        <p className="label-caps text-ink-soft">
          {slots.length} {slots.length === 1 ? "slot" : "slots"}
        </p>
      </div>
      <ul className="flex flex-col">
        {slots.map((s) => (
          <CartRow key={s.startAt} slot={s} />
        ))}
      </ul>
      <div className="flex items-baseline justify-between border-t border-rule pt-2xs">
        <span className="label-caps text-ink-soft">Total</span>
        <span className="stadium-display text-3xl uppercase text-ink" data-testid="cart-total">
          {formatPriceBdt(total)}
        </span>
      </div>
      {error && <HoldErrorBanner message={error} />}
      <Button
        onClick={onContinue}
        loading={busy}
        size="lg"
        data-testid="cart-continue"
      >
        {accessToken ? "Hold for 8 minutes" : "Sign in to continue"}
      </Button>
    </aside>
  );
}

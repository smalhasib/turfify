"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useAuthHydrated, useAuthStore } from "@/lib/authStore";
import { createHold, validateDiscountCode } from "@/lib/bookings";
import { formatPriceBdt } from "@/lib/calendar";
import { type CartSlot, useCartStore } from "@/lib/cartStore";

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

type DiscountState =
  | { kind: "none" }
  | { kind: "checking"; code: string }
  | { kind: "ok"; code: string; amount: number }
  | { kind: "error"; code: string; message: string };

export function CartPanel() {
  const router = useRouter();
  const hydrated = useAuthHydrated();
  const accessToken = useAuthStore((s) => s.accessToken);
  const venueId = useCartStore((s) => s.venueId);
  const slots = useCartStore((s) => s.slots);
  const subtotal = useCartStore((s) => s.total());
  const clear = useCartStore((s) => s.clear);

  const [discount, setDiscount] = useState<DiscountState>({ kind: "none" });
  const [codeDraft, setCodeDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const total = useMemo(() => {
    if (discount.kind !== "ok") return subtotal;
    return Math.max(0, subtotal - discount.amount);
  }, [subtotal, discount]);

  const slotDates = useMemo(
    () =>
      Array.from(
        new Set(
          slots.map((s) => new Date(s.startAt).toISOString().slice(0, 10)),
        ),
      ),
    [slots],
  );

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

  async function onApplyCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = codeDraft.trim().toUpperCase();
    if (!code) return;
    if (!accessToken) {
      router.push("/login");
      return;
    }

    setDiscount({ kind: "checking", code });
    try {
      const data = await validateDiscountCode({
        code,
        subtotal_bdt: subtotal,
        slot_dates: slotDates,
      });
      setDiscount({ kind: "ok", code: data.code, amount: data.amount_off_bdt });
    } catch (err: unknown) {
      type ErrLike = { response?: { data?: { detail?: string } }; message?: string };
      const e2 = err as ErrLike;
      const detail = e2?.response?.data?.detail ?? e2?.message ?? "Code invalid";
      setDiscount({ kind: "error", code, message: detail });
    }
  }

  function clearCode() {
    setDiscount({ kind: "none" });
    setCodeDraft("");
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
        discount_code: discount.kind === "ok" ? discount.code : null,
      });
      clear();
      router.push(`/booking/${result.booking_id}`);
    } catch (err: unknown) {
      type ErrLike = { response?: { data?: { detail?: string } }; message?: string };
      const e2 = err as ErrLike;
      const detail = e2?.response?.data?.detail ?? e2?.message ?? "Hold failed";
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

      {/* Discount code */}
      {discount.kind !== "ok" ? (
        <form
          onSubmit={onApplyCode}
          className="flex flex-col gap-2xs"
          data-testid="discount-form"
        >
          <label className="label-caps text-ink-soft" htmlFor="discount-input">
            Discount code
          </label>
          <div className="flex gap-2xs">
            <Input
              id="discount-input"
              data-testid="discount-input"
              value={codeDraft}
              onChange={(e) => setCodeDraft(e.target.value)}
              placeholder="WEEKEND10"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              maxLength={64}
              invalid={discount.kind === "error"}
            />
            <Button
              type="submit"
              variant="outline"
              loading={discount.kind === "checking"}
              disabled={!codeDraft.trim()}
              data-testid="discount-apply"
            >
              Apply
            </Button>
          </div>
          {discount.kind === "error" && (
            <p className="text-xs text-[var(--color-danger)]" data-testid="discount-error">
              {discount.message}
            </p>
          )}
        </form>
      ) : (
        <div
          className="flex items-center justify-between rounded-xs border border-success/40 bg-bg px-sm py-2xs"
          data-testid="discount-applied"
        >
          <div className="flex flex-col">
            <span className="label-caps text-success">Code applied</span>
            <span className="text-sm font-medium text-ink">{discount.code}</span>
          </div>
          <button
            type="button"
            onClick={clearCode}
            className="text-xs uppercase tracking-wide text-ink-soft hover:text-[var(--color-danger)]"
          >
            Remove
          </button>
        </div>
      )}

      {/* Totals */}
      <div className="flex flex-col gap-2xs border-t border-rule pt-2xs">
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-ink-soft">Subtotal</span>
          <span className="font-medium text-ink" data-testid="cart-subtotal">
            {formatPriceBdt(subtotal)}
          </span>
        </div>
        {discount.kind === "ok" && (
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-ink-soft">Discount</span>
            <span
              className="font-medium text-success"
              data-testid="cart-discount"
            >
              − {formatPriceBdt(discount.amount)}
            </span>
          </div>
        )}
        <div className="flex items-baseline justify-between">
          <span className="label-caps text-ink-soft">Total</span>
          <span
            className="stadium-display text-3xl uppercase text-ink"
            data-testid="cart-total"
          >
            {formatPriceBdt(total)}
          </span>
        </div>
      </div>

      {error && (
        <p
          role="alert"
          data-testid="cart-error"
          className="rounded-xs border border-[var(--color-danger)] bg-bg px-sm py-xs text-sm text-[var(--color-danger)]"
        >
          {error}
        </p>
      )}

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

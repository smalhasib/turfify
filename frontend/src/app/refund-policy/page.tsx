import { LegalLayout } from "@/components/ui/LegalLayout";

export const metadata = {
  title: "Refund Policy — Turfify",
};

export default function RefundPage() {
  return (
    <LegalLayout kicker="Legal" title="Refund Policy" updatedAt="2026-05-07">
      <p>
        Below is the full refund policy. The cancellation flow inside the app
        always shows you the exact refund preview before you confirm — this
        page exists for the legal record.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Tiers
      </h2>
      <ul className="list-disc pl-md">
        <li>
          <strong>More than 24 hours before slot start:</strong> 100% refund
          of the slot price.
        </li>
        <li>
          <strong>Within 24 hours of slot start:</strong> 0% refund. The slot
          is forfeit.
        </li>
      </ul>
      <p>
        Multi-day bookings are evaluated per-slot. If your booking has slots
        on different days, each slot uses its own start time. The total
        refund is the sum across eligible slots.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Mechanics
      </h2>
      <ul className="list-disc pl-md">
        <li>
          <strong>Cash bookings (paid at gate):</strong> staff will return
          cash at the venue or via the venue&apos;s personal bKash. The
          cancellation creates a pending refund visible to admins.
        </li>
        <li>
          <strong>Online bookings (bKash):</strong> automatic refund through
          the bKash refund API. Funds typically settle within 3–7 banking
          days.
        </li>
        <li>
          <strong>Unpaid cash bookings (cash on arrival, never paid):</strong>
          cancellation is immediate; no refund is required since no money was
          collected.
        </li>
      </ul>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        System-side cancellations
      </h2>
      <p>
        If we cancel your booking due to a system fault — slot conflict,
        flooding, equipment failure, mandated closure — you receive a full
        100% refund regardless of timing. Admins issue these directly.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Contact
      </h2>
      <p>
        For disputes or assistance: <strong>support@smalhasib.com</strong>
      </p>
    </LegalLayout>
  );
}

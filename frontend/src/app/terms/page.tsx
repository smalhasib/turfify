import { LegalLayout } from "@/components/ui/LegalLayout";

export const metadata = {
  title: "Terms of Service — Turfify",
};

export default function TermsPage() {
  return (
    <LegalLayout kicker="Legal" title="Terms of Service" updatedAt="2026-05-07">
      <p>
        By creating a booking on Turfify you agree to these Terms. If you
        don&apos;t, don&apos;t book.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Bookings
      </h2>
      <ul className="list-disc pl-md">
        <li>
          Slot availability is shown live. A confirmed booking holds the
          pitch; a hold (online payment in progress) holds it for 8 minutes.
        </li>
        <li>
          You must arrive on time. We are not responsible for missed slots.
        </li>
        <li>
          The customer who places the booking is responsible for the entire
          group and is bound by these Terms.
        </li>
      </ul>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Payment
      </h2>
      <ul className="list-disc pl-md">
        <li>
          Online payments are processed by bKash. Receipts are issued
          automatically once payment confirms.
        </li>
        <li>
          Cash bookings must be paid at the gate. If cash is not received by
          the cutoff (default 15 minutes before kickoff), the booking
          auto-cancels and the slot is released.
        </li>
      </ul>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Cancellation &amp; refunds
      </h2>
      <ul className="list-disc pl-md">
        <li>
          Cancellation more than 24 hours before slot start: full refund of
          the eligible portion.
        </li>
        <li>
          Cancellation within 24 hours: no refund.
        </li>
        <li>
          For multi-day bookings each slot is judged separately; the refund
          total sums per-slot eligibility.
        </li>
        <li>
          Refunds for cash payments are returned at the venue. Online refunds
          flow back to the original payment method.
        </li>
        <li>
          We reserve the right to issue full refunds for system faults (slot
          oversold, equipment failure, weather closure).
        </li>
      </ul>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Conduct
      </h2>
      <p>
        Disrespectful, dangerous, or destructive behaviour at the venue is
        grounds for immediate ejection without refund and may result in your
        account being disabled.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        No-show policy
      </h2>
      <p>
        Repeated no-shows on cash bookings (3 instances) automatically
        disable cash booking on your account. You can still book via online
        payment. Contact support to request reinstatement.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Changes
      </h2>
      <p>
        Pricing and policies can change. Confirmed bookings retain the price
        you saw at the time of booking.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Governing law
      </h2>
      <p>
        These Terms are governed by the laws of Bangladesh. Disputes will be
        addressed in Dhaka jurisdiction.
      </p>
    </LegalLayout>
  );
}

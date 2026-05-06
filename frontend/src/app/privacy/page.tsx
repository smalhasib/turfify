import { LegalLayout } from "@/components/ui/LegalLayout";

export const metadata = {
  title: "Privacy Policy — Turfify",
};

export default function PrivacyPage() {
  return (
    <LegalLayout
      kicker="Legal"
      title="Privacy Policy"
      updatedAt="2026-05-07"
    >
      <p>
        This Privacy Policy describes how Turfify (&quot;we&quot;, &quot;us&quot;)
        collects, uses, and stores personal information when you book turf time
        through our platform.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        What we collect
      </h2>
      <ul className="list-disc pl-md">
        <li>
          <strong>Phone number</strong>, used for sign-in via Firebase phone OTP.
        </li>
        <li>
          <strong>Optional name and email</strong>, if you choose to add them.
        </li>
        <li>
          <strong>Booking history</strong>: dates, slots, prices, payment
          method, and outcomes (confirmed, cancelled, refunded).
        </li>
        <li>
          <strong>Payment metadata</strong>: bKash transaction IDs (when
          applicable). We do not store card numbers, MFS PINs, or full bank
          details — those flow through bKash.
        </li>
      </ul>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        How we use it
      </h2>
      <ul className="list-disc pl-md">
        <li>To run the booking flow: hold slots, accept payment, issue receipts.</li>
        <li>To prevent abuse (no-show tracking and cash-blacklist threshold).</li>
        <li>For internal reporting on revenue and occupancy.</li>
        <li>To respond to your support requests.</li>
      </ul>
      <p>
        We do not sell or rent your personal information to third parties.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Third-party services
      </h2>
      <ul className="list-disc pl-md">
        <li>
          <strong>Firebase Authentication</strong> (Google) — phone OTP delivery
          + verification.
        </li>
        <li>
          <strong>bKash</strong> — payment processing (when you pay online).
        </li>
        <li>
          <strong>Cloudflare</strong> — DDoS protection and TLS for our domain.
        </li>
      </ul>
      <p>
        Each third party processes your data under its own privacy terms; we
        only forward what is needed for the action you initiated (e.g., your
        phone number is sent to Firebase to deliver the OTP).
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Data retention
      </h2>
      <p>
        Active bookings, payment records, and audit logs are retained
        indefinitely for revenue, accounting, and dispute purposes.
      </p>
      <p>
        You can request deletion of your account from your profile page. After
        a 30-day cool-off period, we anonymize your personal information
        (name, phone, email, Firebase UID) while keeping booking records
        attached to an anonymous user ID for the integrity of historical
        revenue reports.
      </p>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Your rights
      </h2>
      <ul className="list-disc pl-md">
        <li>Access and correct your data via your profile page.</li>
        <li>Request deletion (cooling-off + anonymization as above).</li>
        <li>Contact our team for any data-handling question.</li>
      </ul>

      <h2 className="stadium-display mt-md text-2xl uppercase text-ink">
        Contact
      </h2>
      <p>
        Questions or requests: <strong>support@smalhasib.com</strong>
      </p>
    </LegalLayout>
  );
}

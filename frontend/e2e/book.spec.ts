import { expect, test, type Page } from "@playwright/test";

const SAMPLE_RESPONSE = {
  venue_id: 1,
  venue_name: "Turfify Main",
  timezone: "Asia/Dhaka",
  days: [] as unknown[],
};

function buildSampleCalendar(start: string, days: number) {
  const out: typeof SAMPLE_RESPONSE = {
    ...SAMPLE_RESPONSE,
    days: [],
  };
  const [y, m, d] = start.split("-").map(Number);
  for (let i = 0; i < days; i++) {
    const date = new Date(Date.UTC(y!, m! - 1, d! + i));
    const iso = date.toISOString().slice(0, 10);
    const slots: unknown[] = [];
    // 6 slots from 16:00 -> 22:00 Dhaka (10:00 -> 16:00 UTC)
    for (let hr = 16; hr < 22; hr++) {
      const startUtc = new Date(Date.UTC(y!, m! - 1, d! + i, hr - 6));
      const endUtc = new Date(startUtc.getTime() + 60 * 60 * 1000);
      slots.push({
        start_at: startUtc.toISOString(),
        end_at: endUtc.toISOString(),
        status: hr === 17 ? "booked" : hr === 18 ? "blocked" : "available",
        price_bdt: hr >= 18 ? 1500 : 1000,
      });
    }
    out.days.push({ date: iso, is_closed: i === 3, slots: i === 3 ? [] : slots });
  }
  return out;
}

async function stubCalendar(page: Page) {
  await page.route("**/v1/venues/1/calendar*", async (route) => {
    const url = new URL(route.request().url());
    const fromDate = url.searchParams.get("from")!;
    const toDate = url.searchParams.get("to")!;
    const [fy, fm, fd] = fromDate.split("-").map(Number);
    const [ty, tm, td] = toDate.split("-").map(Number);
    const start = Date.UTC(fy!, fm! - 1, fd!);
    const end = Date.UTC(ty!, tm! - 1, td!);
    const days = Math.round((end - start) / 86400000) + 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildSampleCalendar(fromDate, days)),
    });
  });
}

test.describe("Phase 3 booking calendar", () => {
  test.beforeEach(async ({ page }) => {
    await stubCalendar(page);
  });

  test("renders day picker + slot grid for selected day", async ({ page }) => {
    await page.goto("/book");

    await expect(page.getByRole("heading", { name: /pick the pitch/i })).toBeVisible();
    await expect(page.getByTestId("day-tab")).toHaveCount(7);
    await expect(page.getByTestId("slot-grid")).toBeVisible();
    await expect(page.getByTestId("slot-cell")).toHaveCount(6);
  });

  test("each slot shows price + status pill", async ({ page }) => {
    await page.goto("/book");

    const firstSlot = page.getByTestId("slot-cell").first();
    await expect(firstSlot).toContainText("BDT");
    await expect(page.getByTestId("slot-status").first()).toBeVisible();
  });

  test("clicking a different day swaps the slot grid", async ({ page }) => {
    await page.goto("/book");
    const tabs = page.getByTestId("day-tab");
    await expect(tabs).toHaveCount(7);

    // The 4th day (i=3) is mocked as closed → slot grid disappears, closed banner shows.
    await tabs.nth(3).click();
    await expect(page.getByTestId("day-closed")).toBeVisible();
    await expect(page.getByTestId("slot-grid")).not.toBeVisible();
  });

  test("booked + blocked slots are disabled", async ({ page }) => {
    await page.goto("/book");
    const cells = page.getByTestId("slot-cell");
    await expect(cells).toHaveCount(6);
    const booked = cells.filter({ has: page.getByText("BOOKED", { exact: true }) });
    await expect(booked).toBeDisabled();
    const blocked = cells.filter({ has: page.getByText("BLOCKED", { exact: true }) });
    await expect(blocked).toBeDisabled();
  });
});

test.describe("Phase 4 cart + hold", () => {
  test.beforeEach(async ({ page }) => {
    await stubCalendar(page);
  });

  test("clicking an open slot adds it to the cart with running total", async ({ page }) => {
    await page.goto("/book");

    // Cart starts empty.
    await expect(page.getByTestId("cart-empty")).toBeVisible();

    // First OPEN slot is 16:00 (BDT 1,000). 17:00 booked, 18:00 blocked,
    // 19:00 next OPEN at BDT 1,500.
    const open = page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("OPEN", { exact: true }) })
      .first();
    await open.click();

    await expect(page.getByTestId("cart-panel")).toBeVisible();
    await expect(page.getByTestId("cart-total")).toHaveText("BDT 1,000");

    // Tap a second OPEN slot (19:00 = 1500 BDT).
    const second = page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("OPEN", { exact: true }) })
      .nth(1);
    await second.click();
    await expect(page.getByTestId("cart-total")).toHaveText("BDT 2,500");

    // PICKED label appears on the chosen slot.
    await expect(
      page
        .getByTestId("slot-cell")
        .filter({ has: page.getByText("PICKED", { exact: true }) })
        .first(),
    ).toBeVisible();

    // Tap the first PICKED again to remove it (only the 19:00 one stays).
    await page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("PICKED", { exact: true }) })
      .first()
      .click();
    await expect(page.getByTestId("cart-total")).toHaveText("BDT 1,500");
  });

  test("Continue redirects unauthenticated users to /login", async ({ page }) => {
    await page.goto("/book");
    const open = page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("OPEN", { exact: true }) })
      .first();
    await open.click();

    await page.getByTestId("cart-continue").click();
    await page.waitForURL("**/login", { timeout: 10_000 });
  });

  test("apply discount code shows reduced total + persists into hold call", async ({ page }) => {
    await page.addInitScript(() => {
      const value = {
        state: {
          accessToken: "stub-access-token",
          refreshToken: "stub-refresh-token",
          user: { id: 99, phone: "+8801712345678", name: null, email: null, role: "customer" },
        },
        version: 0,
      };
      window.localStorage.setItem("turfify-auth", JSON.stringify(value));
    });

    let lastHoldBody: unknown = null;

    await page.route("**/v1/discount-codes/validate", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          code: "OFF20",
          type: "percent",
          amount_off_bdt: 200,
          final_total_bdt: 800,
        }),
      });
    });

    await page.route("**/v1/bookings/hold", async (route) => {
      lastHoldBody = JSON.parse(route.request().postData() ?? "{}");
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          booking_id: 51,
          public_id: "TRF-2026-000051",
          hold_token: "abc",
          hold_expires_at: new Date(Date.now() + 8 * 60 * 1000).toISOString(),
          subtotal_bdt: 1000,
          discount_code: "OFF20",
          discount_amount_bdt: 200,
          total_bdt: 800,
          slot_count: 1,
        }),
      });
    });

    await page.route("**/v1/bookings/51/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          booking_id: 51,
          public_id: "TRF-2026-000051",
          status: "pending_payment",
          venue_id: 1,
          total_bdt: 800,
          subtotal_bdt: 1000,
          discount_amount_bdt: 200,
          admin_adjustment_bdt: 0,
          slot_count: 1,
          first_slot_at: "2026-05-12T10:00:00Z",
          last_slot_at: "2026-05-12T11:00:00Z",
          hold_expires_at: new Date(Date.now() + 8 * 60 * 1000).toISOString(),
          seconds_to_expiry: 480,
          slots: [
            { slot_start_at: "2026-05-12T10:00:00Z", slot_end_at: "2026-05-12T11:00:00Z", price_bdt: 1000 },
          ],
          created_at: new Date().toISOString(),
        }),
      });
    });

    await page.goto("/book");
    const open = page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("OPEN", { exact: true }) })
      .first();
    await open.click();

    await page.getByTestId("discount-input").fill("off20");
    await page.getByTestId("discount-apply").click();

    await expect(page.getByTestId("discount-applied")).toBeVisible();
    await expect(page.getByTestId("cart-discount")).toContainText("BDT 200");
    await expect(page.getByTestId("cart-total")).toHaveText("BDT 800");

    await page.getByTestId("cart-continue").click();
    await page.waitForURL("**/booking/51", { timeout: 10_000 });

    type HoldBody = { discount_code?: string };
    expect((lastHoldBody as HoldBody).discount_code).toBe("OFF20");
    await expect(page.getByTestId("booking-discount-line")).toBeVisible();
    await expect(page.getByTestId("booking-total")).toHaveText("BDT 800");
  });

  test("invalid discount code shows inline error + total stays at subtotal", async ({ page }) => {
    await page.addInitScript(() => {
      const value = {
        state: {
          accessToken: "stub-access-token",
          refreshToken: "stub-refresh-token",
          user: { id: 99, phone: "+8801712345678", name: null, email: null, role: "customer" },
        },
        version: 0,
      };
      window.localStorage.setItem("turfify-auth", JSON.stringify(value));
    });

    await page.route("**/v1/discount-codes/validate", async (route) => {
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "discount_not_found" }),
      });
    });

    await page.goto("/book");
    const open = page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("OPEN", { exact: true }) })
      .first();
    await open.click();

    await page.getByTestId("discount-input").fill("nope");
    await page.getByTestId("discount-apply").click();

    await expect(page.getByTestId("discount-error")).toBeVisible();
    await expect(page.getByTestId("cart-total")).toHaveText("BDT 1,000");
  });

  test("Cash booking creates confirmed booking + shows awaiting-payment banner", async ({ page }) => {
    await page.addInitScript(() => {
      const value = {
        state: {
          accessToken: "stub-access-token",
          refreshToken: "stub-refresh-token",
          user: { id: 99, phone: "+8801712345678", name: null, email: null, role: "customer" },
        },
        version: 0,
      };
      window.localStorage.setItem("turfify-auth", JSON.stringify(value));
    });

    let lastHoldBody: unknown = null;
    await page.route("**/v1/bookings/hold", async (route) => {
      lastHoldBody = JSON.parse(route.request().postData() ?? "{}");
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          booking_id: 42,
          public_id: "TRF-2026-000042",
          payment_method: "cash",
          hold_token: null,
          hold_expires_at: null,
          subtotal_bdt: 1000,
          discount_code: null,
          discount_amount_bdt: 0,
          total_bdt: 1000,
          slot_count: 1,
        }),
      });
    });

    await page.route("**/v1/bookings/42/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          booking_id: 42,
          public_id: "TRF-2026-000042",
          status: "confirmed",
          payment_collection: "cash_pending",
          venue_id: 1,
          total_bdt: 1000,
          subtotal_bdt: 1000,
          discount_amount_bdt: 0,
          admin_adjustment_bdt: 0,
          slot_count: 1,
          first_slot_at: "2026-05-12T10:00:00Z",
          last_slot_at: "2026-05-12T11:00:00Z",
          hold_expires_at: null,
          seconds_to_expiry: null,
          slots: [
            { slot_start_at: "2026-05-12T10:00:00Z", slot_end_at: "2026-05-12T11:00:00Z", price_bdt: 1000 },
          ],
          created_at: new Date().toISOString(),
        }),
      });
    });

    await page.goto("/book");
    const open = page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("OPEN", { exact: true }) })
      .first();
    await open.click();

    // Cash is the default — verify the picker reflects that.
    await expect(page.getByTestId("pay-cash")).toHaveAttribute("data-selected", "true");

    await page.getByTestId("cart-continue").click();

    type HoldBody = { payment_method?: string };
    await page.waitForURL("**/booking/42", { timeout: 10_000 });
    expect((lastHoldBody as HoldBody).payment_method).toBe("cash");

    await expect(page.getByTestId("booking-public-id")).toHaveText("TRF-2026-000042");
    await expect(page.getByTestId("cash-awaiting")).toBeVisible();
    await expect(page.getByTestId("hold-countdown")).not.toBeVisible();
    await expect(page.getByTestId("booking-total")).toHaveText("BDT 1,000");
  });

  test("bKash option is disabled for now", async ({ page }) => {
    await page.addInitScript(() => {
      const value = {
        state: {
          accessToken: "stub-access-token",
          refreshToken: "stub-refresh-token",
          user: { id: 99, phone: "+8801712345678", name: null, email: null, role: "customer" },
        },
        version: 0,
      };
      window.localStorage.setItem("turfify-auth", JSON.stringify(value));
    });

    await page.goto("/book");
    const open = page
      .getByTestId("slot-cell")
      .filter({ has: page.getByText("OPEN", { exact: true }) })
      .first();
    await open.click();

    await expect(page.getByTestId("pay-online")).toBeDisabled();
    await expect(page.getByTestId("pay-cash")).toHaveAttribute("data-selected", "true");
  });
});

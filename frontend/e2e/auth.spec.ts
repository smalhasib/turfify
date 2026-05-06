import { expect, test, type Page } from "@playwright/test";

/**
 * E2E tests for the Phase 2 auth UI plumbing.
 *
 * The Firebase Phone Auth + reCAPTCHA is browser-side and challenges automated
 * sessions even with test phone numbers in some configurations, so for CI we
 * stub the server-side `/auth/firebase` exchange and the Firebase Web SDK
 * confirmation step. The end-to-end coverage here is:
 *   form -> JWT exchange -> tokens persisted -> /me renders user
 * which is everything except the real Firebase OTP delivery (verified
 * manually before client demo + on every Phase 14 tunnel demo).
 *
 * Real Firebase OTP coverage runs only on chromium, only when
 * `PLAYWRIGHT_REAL_FIREBASE=1` is set, against a Firebase Auth emulator
 * (Phase 14 will wire that up).
 */

const TEST_PHONE = "+8801712345678";
const TEST_USER_ID = 99;

async function stubAuthEndpoints(page: Page) {
  await page.route("**/v1/auth/firebase", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "stub-access-token",
        refresh_token: "stub-refresh-token",
        token_type: "bearer",
        expires_in: 900,
      }),
    }),
  );

  await page.route("**/v1/me", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: TEST_USER_ID,
          phone: TEST_PHONE,
          name: null,
          email: null,
          role: "customer",
          created_at: new Date().toISOString(),
        }),
      });
    }
    return route.continue();
  });

  await page.route("**/v1/auth/logout", (route) =>
    route.fulfill({ status: 204, body: "" }),
  );

  // Skip the Firebase Web SDK by overriding our auth helpers before the page
  // bundle loads. `startPhoneAuth` returns a fake ConfirmationResult whose
  // confirm() returns a user object exposing getIdToken().
  await page.addInitScript(() => {
    (
      window as unknown as { __TURFIFY_E2E_STUB__?: boolean }
    ).__TURFIFY_E2E_STUB__ = true;
  });
}

test.describe("Phase 2 auth UI", () => {
  test.beforeEach(async ({ context }) => {
    await context.clearCookies();
    await context.clearPermissions();
  });

  test("login form rejects malformed phone", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("phone-input").fill("+88012345"); // too short
    await page.getByTestId("send-code").click();
    await expect(page.getByTestId("login-error")).toContainText("+8801");
  });

  test("OTP entry exchanges Firebase token and lands on /me", async ({ page }) => {
    await stubAuthEndpoints(page);

    // Inject a fake Firebase confirmation chain so the page never calls real Firebase.
    await page.addInitScript(() => {
      (window as unknown as Record<string, unknown>).__FIREBASE_TEST_HOOKS__ = {
        startPhoneAuth: () =>
          Promise.resolve({
            confirm: () =>
              Promise.resolve({
                user: { getIdToken: () => Promise.resolve("fake-firebase-id-token") },
              }),
          }),
      };
    });

    await page.goto("/login");
    await page.getByTestId("phone-input").fill(TEST_PHONE);
    await page.getByTestId("send-code").click();

    await expect(page.getByTestId("otp-form")).toBeVisible({ timeout: 10_000 });

    await page.getByTestId("otp-input").fill("123456");
    await page.getByTestId("verify-code").click();

    await page.waitForURL("**/me", { timeout: 10_000 });
    await expect(page.getByTestId("me-phone")).toHaveText(TEST_PHONE);
    await expect(page.getByTestId("me-role")).toHaveText("Player");
  });

  test("logout clears session", async ({ page }) => {
    await stubAuthEndpoints(page);

    await page.addInitScript(
      ({ phone, userId }) => {
        const value = {
          state: {
            accessToken: "stub-access-token",
            refreshToken: "stub-refresh-token",
            user: {
              id: userId,
              phone,
              name: null,
              email: null,
              role: "customer",
            },
          },
          version: 0,
        };
        window.localStorage.setItem("turfify-auth", JSON.stringify(value));
      },
      { phone: TEST_PHONE, userId: TEST_USER_ID },
    );

    await page.goto("/me");
    await expect(page.getByTestId("me-phone")).toHaveText(TEST_PHONE);

    await page.getByTestId("logout").click();
    await page.waitForURL("**/login", { timeout: 10_000 });
  });

  test("/me without auth redirects to /login", async ({ page }) => {
    // No init script, no localStorage seed — visit should redirect.
    await page.goto("/me");
    await page.waitForURL("**/login", { timeout: 10_000 });
  });
});

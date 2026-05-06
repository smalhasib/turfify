import { describe, expect, it } from "vitest";

import { validateBdPhone } from "@/lib/auth";

describe("validateBdPhone", () => {
  it.each([
    "+8801712345678",
    "+8801300000000",
    "+8801999999999",
    "+8801500000000",
  ])("accepts %s", (phone) => {
    expect(validateBdPhone(phone)).toBe(true);
  });

  it.each([
    "01712345678", // missing +880
    "+88017123456789", // too long
    "+880171234567", // too short
    "+8801212345678", // 12 not in [3-9]
    "+14155551234", // not BD
    "",
  ])("rejects %s", (phone) => {
    expect(validateBdPhone(phone)).toBe(false);
  });
});

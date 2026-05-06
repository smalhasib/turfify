import { describe, expect, it } from "vitest";

import { addDaysIso, formatLocalHour, formatPriceBdt } from "@/lib/calendar";

describe("addDaysIso", () => {
  it("adds days, crossing months", () => {
    expect(addDaysIso("2026-05-30", 3)).toBe("2026-06-02");
  });
  it("adds zero days", () => {
    expect(addDaysIso("2026-05-30", 0)).toBe("2026-05-30");
  });
  it("subtracts days", () => {
    expect(addDaysIso("2026-05-02", -3)).toBe("2026-04-29");
  });
});

describe("formatPriceBdt", () => {
  it("inserts thousands separators", () => {
    expect(formatPriceBdt(1500)).toBe("BDT 1,500");
    expect(formatPriceBdt(12000)).toBe("BDT 12,000");
  });
  it("handles zero", () => {
    expect(formatPriceBdt(0)).toBe("BDT 0");
  });
});

describe("formatLocalHour", () => {
  it("formats UTC ISO into Dhaka local time", () => {
    // 2026-05-12 13:00 UTC = 19:00 Asia/Dhaka
    const out = formatLocalHour("2026-05-12T13:00:00Z", "Asia/Dhaka");
    expect(out).toMatch(/7:00.*PM|7:00 PM/);
  });
});

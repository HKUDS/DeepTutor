import { describe, expect, it } from "vitest";
import {
  formatPriceFen,
  slugifyPlanName,
} from "@/lib/payment-admin-api";

describe("payment-admin-api formatting helpers", () => {
  describe("formatPriceFen", () => {
    it("renders whole yuan without decimals", () => {
      expect(formatPriceFen(2900)).toBe("¥29");
    });

    it("renders fen decimals", () => {
      expect(formatPriceFen(2990)).toBe("¥29.90");
    });

    it("handles zero", () => {
      expect(formatPriceFen(0)).toBe("¥0");
    });

    it("handles fractional fen rounding to two decimals", () => {
      expect(formatPriceFen(12_345)).toBe("¥123.45");
    });
  });

  describe("slugifyPlanName", () => {
    it("lowercases and dashes", () => {
      expect(slugifyPlanName("Monthly Star")).toBe("monthly-star");
    });

    it("strips non-alphanumeric (Chinese collapses to surrounding latin)", () => {
      expect(slugifyPlanName("VIP 年度 会员")).toBe("vip");
    });

    it("returns empty for empty input", () => {
      expect(slugifyPlanName("")).toBe("");
      expect(slugifyPlanName("   ")).toBe("");
    });

    it("caps at 64 chars", () => {
      const long = "a".repeat(100);
      expect(slugifyPlanName(long).length).toBe(64);
    });

    it("removes leading/trailing dashes", () => {
      expect(slugifyPlanName("---Plan---")).toBe("plan");
    });
  });
});
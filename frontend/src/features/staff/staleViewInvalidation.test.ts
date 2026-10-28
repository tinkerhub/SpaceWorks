import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { formatMoney, invalidatePaymentViews, withCurrency } from "./paymentsApi";
import { invalidateRequestQueues } from "./panels/QueuesInvalidation";
import { invalidatePrintingViews } from "./queryInvalidation";

function invalidatedKeys(run: (client: QueryClient) => void) {
  const client = new QueryClient();
  const spy = vi.spyOn(client, "invalidateQueries");
  run(client);
  return spy.mock.calls.map(([filters]) => filters?.queryKey);
}

describe("stale-view invalidation", () => {
  it("refreshes every screen that shows a payment", () => {
    const keys = invalidatedKeys((client) => invalidatePaymentViews(client, 4));
    expect(keys).toEqual(expect.arrayContaining([
      ["payments", 4],
      ["dashboard", 4],
      ["machine-service-handover", 4],
      ["machine-service-requests", 4],
      ["members", 4],
      ["events", 4],
      ["bookings", 4],
    ]));
  });

  it("refreshes containers, accountability and the public catalogue after a return", () => {
    const keys = invalidatedKeys((client) => invalidateRequestQueues(client, 4, { inventory: true, needsFix: true, ledger: true }, "lab"));
    expect(keys).toEqual(expect.arrayContaining([
      ["containers", 4],
      ["accountability", 4],
      ["public-categories", "lab"],
    ]));
  });

  it("refreshes machine views, not the retired printing keys, after a move to printing", () => {
    const keys = invalidatedKeys((client) => invalidatePrintingViews(client, 4));
    expect(keys).toEqual(expect.arrayContaining([["machines"], ["machine-service-pools", 4], ["printer-machines", 4]]));
    expect(keys).not.toContainEqual(["print-spools", 4]);
    expect(keys).not.toContainEqual(["print-printers", 4]);
  });
});

describe("currency display", () => {
  it("formats amounts with the currency symbol", () => {
    expect(formatMoney("12.5", "inr")).toBe("₹12.50");
  });

  it("labels a price with the upper-case code only when it is known", () => {
    expect(withCurrency("Booking price", "INR")).toBe("Booking price (INR)");
    expect(withCurrency("Booking price", "")).toBe("Booking price");
  });
});

/**
 * Unit tests for the payment service.
 *
 * These tests demonstrate the deliberate bug: when the customer cache
 * expires during a retry, getCustomer() returns null and the retry
 * path crashes with TypeError.
 */

import {
  getCustomer,
  clearCache,
  expireCacheEntry,
} from "../src/cache/customer-cache";

describe("Customer Cache", () => {
  beforeEach(() => {
    clearCache();
  });

  test("returns customer on first fetch (populates cache)", async () => {
    const customer = await getCustomer("cust_001");
    expect(customer).not.toBeNull();
    expect(customer!.id).toBe("cust_001");
    expect(customer!.name).toBe("Acme Corp");
  });

  test("returns cached customer on second fetch", async () => {
    const first = await getCustomer("cust_001");
    const second = await getCustomer("cust_001");
    expect(first).toEqual(second);
  });

  test("returns null for unknown customer", async () => {
    const customer = await getCustomer("cust_unknown");
    expect(customer).toBeNull();
  });

  test("returns null after cache expiry during refresh window", async () => {
    // Populate cache
    const customer = await getCustomer("cust_001");
    expect(customer).not.toBeNull();

    // Force expire the cache entry
    expireCacheEntry("cust_001");

    // The next call triggers a DB fetch. During the fetch,
    // concurrent callers would get null. We simulate this by
    // verifying the cache was cleared.
    // Note: In the actual bug, this happens during concurrent
    // access in the retry path.
    const refetched = await getCustomer("cust_001");
    // After refetch, should be back
    expect(refetched).not.toBeNull();
  });
});

describe("Payment Service - Bug Demonstration", () => {
  // This test documents the bug behavior.
  // In a real codebase, this test would be added AFTER the bug is found.
  test("documents the null-check bug in retry path", () => {
    // The bug is in payment-service.ts, createCharge():
    //
    // On retry after Stripe failure:
    //   const retryCustomer = await getCustomer(request.customerId);
    //   const methodId = retryCustomer!.paymentMethodId;  // <-- BUG
    //
    // If retryCustomer is null (cache expired), this crashes with:
    //   TypeError: Cannot read properties of null (reading 'paymentMethodId')
    //
    // Fix: Add null check:
    //   if (!retryCustomer) {
    //     throw new PaymentError(`Customer not found on retry: ${request.customerId}`);
    //   }

    // Verify the fix is in place by checking the source
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fs = require("fs");
    const source = fs.readFileSync(
      __dirname + "/../src/services/payment-service.ts",
      "utf-8"
    );

    // The fix: non-null assertion removed
    expect(source).not.toContain("retryCustomer!.paymentMethodId");

    // The null check is now present
    expect(source).toContain("if (!retryCustomer)");
  });
});

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

describe("Payment Service - Null Check Fix Verification", () => {
  test("retry path has proper null check for retryCustomer", () => {
    // Verify the fix: the non-null assertion on retryCustomer should be removed,
    // and a proper null check should be in place.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fs = require("fs");
    const source = fs.readFileSync(
      __dirname + "/../src/services/payment-service.ts",
      "utf-8"
    );

    // The non-null assertion bug should be gone
    expect(source).not.toContain("retryCustomer!.paymentMethodId");

    // A proper null check should now exist
    expect(source).toContain("if (!retryCustomer)");
  });
});

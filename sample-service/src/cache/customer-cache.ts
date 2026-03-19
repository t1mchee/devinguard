/**
 * In-memory customer cache with TTL.
 *
 * BUG (deliberate): TTL was reduced from 300s to 30s in a recent
 * "performance optimization" commit. During TTL refresh windows,
 * getCustomer() returns null. The retry handler in payment-service
 * does NOT null-check the result, causing a TypeError.
 */

export interface Customer {
  id: string;
  name: string;
  email: string;
  tier: "free" | "pro" | "enterprise";
  paymentMethodId: string | null;
}

interface CacheEntry {
  customer: Customer;
  expiresAt: number;
}

// BUG: TTL was reduced from 300_000 (5 min) to 30_000 (30s)
// in commit "perf: reduce customer cache TTL for fresher data"
const CACHE_TTL_MS = 30_000;

const cache = new Map<string, CacheEntry>();

/**
 * Simulate fetching a customer from the database.
 * In production this would be a real DB call.
 */
async function fetchCustomerFromDB(
  customerId: string
): Promise<Customer | null> {
  // Simulate DB latency
  await new Promise((resolve) => setTimeout(resolve, 5));

  // Demo customers
  const customers: Record<string, Customer> = {
    "cust_001": {
      id: "cust_001",
      name: "Acme Corp",
      email: "billing@acme.com",
      tier: "enterprise",
      paymentMethodId: "pm_stripe_001",
    },
    "cust_002": {
      id: "cust_002",
      name: "Startup Inc",
      email: "pay@startup.io",
      tier: "pro",
      paymentMethodId: "pm_stripe_002",
    },
  };

  return customers[customerId] ?? null;
}

/**
 * Get a customer from cache or fetch from DB.
 *
 * Returns null if the customer is not found in DB OR if the cache
 * entry has expired and the DB fetch hasn't completed yet (race
 * condition window during TTL refresh).
 */
export async function getCustomer(
  customerId: string
): Promise<Customer | null> {
  const entry = cache.get(customerId);
  const now = Date.now();

  if (entry && entry.expiresAt > now) {
    return entry.customer;
  }

  // Cache miss or expired — fetch from DB
  // During this window, concurrent calls get null (the bug trigger)
  cache.delete(customerId);

  const customer = await fetchCustomerFromDB(customerId);
  if (customer) {
    cache.set(customerId, {
      customer,
      expiresAt: now + CACHE_TTL_MS,
    });
  }

  return customer;
}

/** Clear all cached entries (for testing). */
export function clearCache(): void {
  cache.clear();
}

/**
 * Force-expire a specific customer's cache entry.
 * Used by the trigger-bug script to simulate TTL expiry.
 */
export function expireCacheEntry(customerId: string): void {
  const entry = cache.get(customerId);
  if (entry) {
    entry.expiresAt = Date.now() - 1;
  }
}

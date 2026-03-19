/**
 * Script to trigger the deliberate bug in the payment service.
 *
 * Steps:
 * 1. Make a successful charge (populates cache)
 * 2. Wait for cache TTL to expire (simulated)
 * 3. Make another charge that triggers a Stripe retry
 * 4. During retry, getCustomer() returns null → TypeError
 *
 * Usage: npm run trigger-bug (requires payment service running on :3001)
 */

const BASE_URL = process.env.PAYMENT_SERVICE_URL || "http://localhost:3001";

async function triggerBug(): Promise<void> {
  console.log("=== DevinGuard Demo: Triggering Payment Service Bug ===\n");

  // Step 1: Successful charge to populate the cache
  console.log("Step 1: Making a successful charge (populating cache)...");
  try {
    const res = await fetch(`${BASE_URL}/charges`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customerId: "cust_001",
        amountCents: 5000,
        currency: "usd",
        description: "Initial charge",
      }),
    });
    const data = await res.json();
    console.log(`  Result: ${res.status}`, data);
  } catch (err) {
    console.log(`  Result: ${err}`);
  }

  // Step 2: Wait for cache to expire (30s TTL)
  console.log("\nStep 2: Waiting 35s for cache TTL to expire...");
  console.log("  (Cache TTL was reduced from 300s to 30s in a recent commit)");
  await new Promise((resolve) => setTimeout(resolve, 35_000));

  // Step 3: Rapid-fire charges to trigger retry + null bug
  console.log("\nStep 3: Sending rapid charges to trigger retry path...");
  console.log("  When Stripe returns a transient error, the retry path");
  console.log("  re-fetches the customer. If cache expired, returns null.");
  console.log("  The missing null check causes TypeError.\n");

  const promises = Array.from({ length: 5 }, (_, i) =>
    fetch(`${BASE_URL}/charges`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customerId: "cust_001",
        amountCents: 1000 * (i + 1),
        currency: "usd",
        description: `Charge attempt ${i + 1}`,
      }),
    })
      .then(async (res) => {
        const data = await res.json();
        const status = res.status >= 500 ? "BUG TRIGGERED" : "OK";
        console.log(`  Charge ${i + 1}: [${status}] ${res.status}`, data);
        return { status: res.status, data };
      })
      .catch((err) => {
        console.log(`  Charge ${i + 1}: [ERROR] ${err}`);
        return { status: 500, error: err };
      })
  );

  const results = await Promise.all(promises);

  // Summary
  const errors = results.filter((r) => r.status >= 500);
  console.log(`\n=== Results: ${errors.length}/5 triggered 500 errors ===`);

  if (errors.length > 0) {
    console.log("\nThe TypeError from the null-check bug should now appear");
    console.log("in Sentry/PagerDuty, triggering the DevinGuard pipeline:");
    console.log("  Alert -> Dedup -> Triage -> Devin Session -> Fix PR");
  } else {
    console.log("\nNo 500 errors this time (retry succeeded before cache expired).");
    console.log("Try running again — the bug is probabilistic due to Stripe retry timing.");
  }
}

triggerBug().catch(console.error);

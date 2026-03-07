/**
 * Payment processing service.
 *
 * Handles charge creation with retry logic. The retry path has a
 * deliberate bug: it calls getCustomer() without null-checking the
 * result before accessing .paymentMethodId.
 */

import { v4 as uuidv4 } from "uuid";
import { getCustomer, Customer } from "../cache/customer-cache";
import { AppError, PaymentError } from "../errors";

export interface ChargeRequest {
  customerId: string;
  amountCents: number;
  currency: string;
  description: string;
  idempotencyKey?: string;
}

export interface ChargeResult {
  chargeId: string;
  status: "succeeded" | "failed" | "pending";
  amountCents: number;
  currency: string;
  customerId: string;
  paymentMethodId: string;
}

/**
 * Simulate calling Stripe to create a charge.
 * Fails ~20% of the time to exercise retry logic.
 */
async function callStripeAPI(
  paymentMethodId: string,
  amountCents: number,
  currency: string
): Promise<{ success: boolean; chargeId: string }> {
  await new Promise((resolve) => setTimeout(resolve, 10));

  // Simulate intermittent failures
  if (Math.random() < 0.2) {
    throw new AppError("Stripe API timeout", 503, true);
  }

  return {
    success: true,
    chargeId: `ch_${uuidv4().slice(0, 12)}`,
  };
}

/**
 * Create a charge for a customer.
 *
 * First attempt fetches the customer and validates the payment method.
 * On retry (after a transient Stripe failure), it re-fetches the
 * customer to get a fresh payment method — BUT does not null-check
 * the result. If the cache entry expired between the first call and
 * the retry, getCustomer() returns null during the refresh window,
 * causing: TypeError: Cannot read properties of null (reading 'paymentMethodId')
 */
export async function createCharge(
  request: ChargeRequest
): Promise<ChargeResult> {
  // Validate
  if (request.amountCents <= 0) {
    throw new PaymentError("Amount must be positive");
  }
  if (!request.currency) {
    throw new PaymentError("Currency is required");
  }

  // First fetch — this one has a null check (correct)
  const customer = await getCustomer(request.customerId);
  if (!customer) {
    throw new PaymentError(
      `Customer not found: ${request.customerId}`
    );
  }

  if (!customer.paymentMethodId) {
    throw new PaymentError(
      `No payment method on file for ${request.customerId}`
    );
  }

  // Attempt charge with retry
  const maxRetries = 3;
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const result = await callStripeAPI(
        customer.paymentMethodId,
        request.amountCents,
        request.currency
      );

      return {
        chargeId: result.chargeId,
        status: "succeeded",
        amountCents: request.amountCents,
        currency: request.currency,
        customerId: request.customerId,
        paymentMethodId: customer.paymentMethodId,
      };
    } catch (err) {
      lastError = err as Error;

      if (attempt < maxRetries) {
        // Re-fetch customer on retry to get a fresh payment method.
        // If cache TTL expired between first fetch and retry,
        // getCustomer() may return null during the refresh window.
        const retryCustomer = await getCustomer(
          request.customerId
        );

        if (!retryCustomer) {
          throw new PaymentError(
            `Customer not found on retry: ${request.customerId}`
          );
        }

        if (!retryCustomer.paymentMethodId) {
          throw new PaymentError(
            `No payment method on file for ${request.customerId} on retry`
          );
        }

        // Back off before retry
        await new Promise((resolve) =>
          setTimeout(resolve, 100 * attempt)
        );
      }
    }
  }

  throw new PaymentError(
    `Charge failed after ${maxRetries} attempts: ${lastError?.message}`
  );
}

/**
 * Express handler for the /charges endpoint.
 */

import { Request, Response, NextFunction } from "express";
import { createCharge, ChargeRequest } from "../services/payment-service";
import { AppError, ValidationError } from "../errors";

export async function handleCreateCharge(
  req: Request,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const { customerId, amountCents, currency, description } = req.body;

    if (!customerId || !amountCents || !currency) {
      throw new ValidationError(
        "Missing required fields: customerId, amountCents, currency"
      );
    }

    const request: ChargeRequest = {
      customerId,
      amountCents: Number(amountCents),
      currency: String(currency),
      description: String(description || ""),
      idempotencyKey: req.headers["idempotency-key"] as string,
    };

    const result = await createCharge(request);
    res.status(201).json(result);
  } catch (err) {
    next(err);
  }
}

/**
 * Global error handler middleware.
 */
export function errorHandler(
  err: Error,
  _req: Request,
  res: Response,
  _next: NextFunction
): void {
  if (err instanceof AppError) {
    res.status(err.statusCode).json({
      error: err.message,
      statusCode: err.statusCode,
    });
  } else {
    // Unhandled error — this is what happens with the bug
    console.error("Unhandled error:", err);
    res.status(500).json({
      error: "Internal server error",
      message: err.message,
      // In production, the stack trace goes to Sentry
      stack: err.stack,
    });
  }
}

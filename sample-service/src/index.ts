/**
 * Payment Service — Express application entry point.
 *
 * A sample microservice with a deliberate bug for DevinGuard demos.
 * The bug: customer cache TTL was reduced, causing null returns
 * during retry logic that doesn't null-check.
 */

import express from "express";
import { handleCreateCharge, errorHandler } from "./handlers/charge-handler";

const app = express();
const PORT = process.env.PORT || 3001;

app.use(express.json());

// Health check
app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "payment-service" });
});

// Charge endpoint
app.post("/charges", handleCreateCharge);

// Global error handler
app.use(errorHandler);

app.listen(PORT, () => {
  console.log(`Payment service running on port ${PORT}`);
});

export default app;

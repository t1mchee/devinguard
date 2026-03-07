# DevinGuard: Autonomous Incident Response

From Alert to Fix PR — Devin as Your On-Call Engineer.

DevinGuard is an orchestration layer that connects production monitoring (PagerDuty, Sentry) to [Devin](https://devin.ai), enabling autonomous incident investigation and code fixes.

## Architecture

```
PagerDuty/Sentry Alert
        |
        v
+-------------------+
| Alert Ingestion   |  Webhook receiver, normalization, deduplication
+-------------------+
        |
        v
+-------------------+
| Context Enrichment|  GitHub commits, Sentry details, service ownership
+-------------------+
        |
        v
+-------------------+
| Triage + Dispatch |  Rule-based + LLM classifier, Devin session creation
+-------------------+
        |
        v
+-------------------+
| Output Routing    |  Slack summary, fix PR, human escalation
+-------------------+
```

## Components

- **orchestrator/** — Python (FastAPI) orchestration service
- **sample-service/** — Node.js/TypeScript payment API with a deliberate bug for demos
- **docs/** — Proposal and cover letter

## Quick Start

### Orchestrator

```bash
cd orchestrator
poetry install
cp .env.example .env  # Fill in API keys
poetry run fastapi dev app/main.py
```

### Sample Service

```bash
cd sample-service
npm install
npm run dev
```

### Running the Demo

```bash
# 1. Start the sample service
cd sample-service && npm run dev

# 2. Start the orchestrator
cd orchestrator && poetry run fastapi dev app/main.py

# 3. Trigger the bug (in another terminal)
cd sample-service && npm run trigger-bug

# 4. Watch the pipeline: PagerDuty alert -> Triage -> Devin session -> Slack + PR
```

## Configuration

See `orchestrator/.env.example` for all required environment variables.

## License

MIT

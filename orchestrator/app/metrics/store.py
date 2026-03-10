"""SQLite-backed metrics store for the operator dashboard.

Stores investigation records and provides aggregation queries for
triage accuracy, ACU spend, session outcomes, and MTTR impact.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings
from app.models.alert import Investigation

logger = logging.getLogger(__name__)

ACU_COST_USD = 0.54  # Team plan: 250 ACUs for $500/month ≈ $0.54/ACU


class MetricsStore:
    """SQLite-backed metrics store."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or settings.metrics_db_path
        self._conn: Optional[sqlite3.Connection] = None

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id TEXT PRIMARY KEY,
                service_name TEXT NOT NULL,
                alert_dedup_key TEXT,
                triage_classification TEXT,
                triage_confidence REAL,
                triage_was_correct INTEGER,
                dispatched_to_devin INTEGER DEFAULT 0,
                session_id TEXT,
                session_outcome TEXT,
                acus_consumed REAL,
                pr_url TEXT,
                pr_merged INTEGER,
                pr_reverted INTEGER,
                human_investigation_time_minutes REAL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_counts (
                dedup_key TEXT PRIMARY KEY,
                alert_count INTEGER DEFAULT 1,
                updated_at TEXT
            )
        """)
        self._conn.commit()
        logger.info(f"Metrics store initialized at {self._db_path}")

    async def record_investigation(self, investigation: Investigation) -> None:
        """Insert a new investigation record."""
        if not self._conn:
            return
        self._conn.execute(
            """INSERT OR REPLACE INTO investigations
            (investigation_id, service_name, alert_dedup_key, triage_classification,
             triage_confidence, dispatched_to_devin, session_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                investigation.investigation_id,
                investigation.service_name,
                investigation.dedup_key,
                investigation.triage_classification,
                investigation.triage_confidence,
                1 if investigation.session_id else 0,
                investigation.session_id,
                investigation.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    async def update_investigation_outcome(
        self, investigation_id: str, **kwargs: object
    ) -> None:
        """Update retroactive fields on an investigation."""
        if not self._conn:
            return

        set_clauses = []
        values = []
        for key, value in kwargs.items():
            if key == "resolved_at" and isinstance(value, datetime):
                value = value.isoformat()
            if key == "triage_was_correct" and isinstance(value, bool):
                value = int(value)
            if key == "pr_merged" and isinstance(value, bool):
                value = int(value)
            if key == "pr_reverted" and isinstance(value, bool):
                value = int(value)
            set_clauses.append(f"{key} = ?")
            values.append(value)

        if not set_clauses:
            return

        values.append(investigation_id)
        self._conn.execute(
            f"UPDATE investigations SET {', '.join(set_clauses)} WHERE investigation_id = ?",
            values,
        )
        self._conn.commit()

    async def get_summary(
        self,
        period_start: datetime,
        period_end: datetime,
        service_name: Optional[str] = None,
    ) -> dict:
        """Aggregate metrics for a time period."""
        if not self._conn:
            return {}

        where = "WHERE created_at >= ? AND created_at <= ?"
        params: list[object] = [period_start.isoformat(), period_end.isoformat()]
        if service_name:
            where += " AND service_name = ?"
            params.append(service_name)

        row = self._conn.execute(
            f"""SELECT
                COUNT(*) as total,
                SUM(CASE WHEN dispatched_to_devin = 1 THEN 1 ELSE 0 END) as dispatched,
                SUM(COALESCE(acus_consumed, 0)) as total_acus,
                SUM(CASE WHEN session_outcome = 'fix_pr' THEN 1 ELSE 0 END) as fix_pr,
                SUM(CASE WHEN session_outcome = 'hypothesis' THEN 1 ELSE 0 END) as hypothesis,
                SUM(CASE WHEN session_outcome = 'inconclusive' THEN 1 ELSE 0 END) as inconclusive,
                SUM(
                    CASE WHEN session_outcome = 'false_dispatch'
                    THEN 1 ELSE 0 END
                ) as false_dispatch,
                AVG(
                    CASE WHEN session_outcome IS NOT NULL
                    THEN human_investigation_time_minutes END
                ) as avg_mttr
            FROM investigations {where}""",
            params,
        ).fetchone()

        total = row["total"] or 0
        dispatched = row["dispatched"] or 0
        total_acus = row["total_acus"] or 0.0

        return {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "service_name": service_name,
            "total_investigations": total,
            "dispatched_to_devin": dispatched,
            "total_acus": total_acus,
            "total_acu_cost_usd": round(total_acus * ACU_COST_USD, 2),
            "outcomes": {
                "fix_pr": row["fix_pr"] or 0,
                "hypothesis": row["hypothesis"] or 0,
                "inconclusive": row["inconclusive"] or 0,
                "false_dispatch": row["false_dispatch"] or 0,
            },
            "avg_mttr_minutes": row["avg_mttr"],
        }

    async def get_triage_accuracy_trend(
        self, weeks: int = 12, service_name: Optional[str] = None
    ) -> list[dict]:
        """Return weekly precision/recall for the last N weeks."""
        if not self._conn:
            return []

        results = []
        now = datetime.utcnow()
        for i in range(weeks):
            week_end = now - timedelta(weeks=i)
            week_start = week_end - timedelta(weeks=1)

            where = "WHERE created_at >= ? AND created_at <= ? AND triage_was_correct IS NOT NULL"
            params: list[object] = [week_start.isoformat(), week_end.isoformat()]
            if service_name:
                where += " AND service_name = ?"
                params.append(service_name)

            row = self._conn.execute(
                f"""SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN triage_was_correct = 1
                        AND dispatched_to_devin = 1
                        THEN 1 ELSE 0 END) as true_pos,
                    SUM(CASE WHEN triage_was_correct = 0
                        AND dispatched_to_devin = 1
                        THEN 1 ELSE 0 END) as false_pos,
                    SUM(CASE WHEN triage_was_correct = 1
                        AND dispatched_to_devin = 0
                        THEN 1 ELSE 0 END) as false_neg
                FROM investigations {where}""",
                params,
            ).fetchone()

            tp = row["true_pos"] or 0
            fp = row["false_pos"] or 0
            fn = row["false_neg"] or 0

            precision = tp / (tp + fp) if (tp + fp) > 0 else None
            recall = tp / (tp + fn) if (tp + fn) > 0 else None

            results.append({
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "precision": precision,
                "recall": recall,
                "labeled_count": row["total"] or 0,
            })

        results.reverse()
        return results

    async def get_acu_spend_trend(
        self, days: int = 30, service_name: Optional[str] = None
    ) -> list[dict]:
        """Return daily ACU spend for the last N days."""
        if not self._conn:
            return []

        results = []
        now = datetime.utcnow()
        for i in range(days):
            day_end = now - timedelta(days=i)
            day_start = day_end - timedelta(days=1)

            where = "WHERE created_at >= ? AND created_at <= ?"
            params: list[object] = [day_start.isoformat(), day_end.isoformat()]
            if service_name:
                where += " AND service_name = ?"
                params.append(service_name)

            row = self._conn.execute(
                f"""SELECT
                    SUM(COALESCE(acus_consumed, 0)) as total_acus,
                    COUNT(*) as investigation_count
                FROM investigations {where}""",
                params,
            ).fetchone()

            acus = row["total_acus"] or 0.0
            results.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "acus": acus,
                "cost_usd": round(acus * ACU_COST_USD, 2),
                "investigations": row["investigation_count"] or 0,
            })

        results.reverse()
        return results

    async def get_service_success_rate(self, service_name: str) -> dict:
        """Get historical success rate for a service (for auto-merge gate)."""
        if not self._conn:
            return {"total_investigations": 0, "success_rate": 0.0}

        row = self._conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(
                    CASE WHEN session_outcome IN ('fix_pr', 'hypothesis')
                    THEN 1 ELSE 0 END
                ) as successes
            FROM investigations
            WHERE service_name = ? AND session_outcome IS NOT NULL""",
            (service_name,),
        ).fetchone()

        total = row["total"] or 0
        successes = row["successes"] or 0
        rate = successes / total if total > 0 else 0.0

        return {
            "total_investigations": total,
            "successful_investigations": successes,
            "success_rate": rate,
        }

    async def list_investigations(
        self,
        limit: int = 50,
        offset: int = 0,
        service_name: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> list[dict]:
        """Paginated list of investigations."""
        if not self._conn:
            return []

        where_clauses = []
        params: list[object] = []

        if service_name:
            where_clauses.append("service_name = ?")
            params.append(service_name)
        if outcome:
            where_clauses.append("session_outcome = ?")
            params.append(outcome)

        where = ""
        if where_clauses:
            where = "WHERE " + " AND ".join(where_clauses)

        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM investigations {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        return [dict(row) for row in rows]

    async def reset(self) -> None:
        """Clear all data from the metrics store (used on server startup for demo)."""
        if not self._conn:
            return
        self._conn.execute("DELETE FROM investigations")
        self._conn.execute("DELETE FROM alert_counts")
        self._conn.commit()
        logger.info("Metrics store reset — all investigations and alert counts cleared")

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

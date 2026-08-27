from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.export import ExportRun
from ..models.quality import QualityFinding
from .engine import Finding


async def persist_findings(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    ingestion_run_id: int,
    findings: list[Finding],
    product_count: int,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            # Feed-keyed delete
            await session.execute(
                delete(QualityFinding).where(QualityFinding.feed_source_id == feed_source_id)
            )

            # Insert findings (product_id already attached by engine)
            for finding in findings:
                session.add(QualityFinding(
                    feed_source_id=feed_source_id,
                    ingestion_run_id=ingestion_run_id,
                    product_id=finding.product_id or "cross_product",
                    severity=finding.severity,
                    code=finding.rule_id,
                    field=finding.field,
                    message=finding.message,
                    details=finding.details,
                ))

            # Count by severity
            counts: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
            for f in findings:
                counts[f.severity] = counts.get(f.severity, 0) + 1

            # Write ExportRun
            session.add(ExportRun(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run_id,
                status="pending_export",
                product_count=product_count,
                critical_finding_count=counts["critical"],
                warning_finding_count=counts["warning"],
                info_finding_count=counts["info"],
                export_version_id=None,
            ))

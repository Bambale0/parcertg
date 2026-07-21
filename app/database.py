from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from app.dedup import similarity
from app.models import Base, Lead, LeadSource, LeadStatus


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def find_duplicate(
        self,
        *,
        fingerprint: str,
        normalized_text: str,
        window_hours: int,
        minimum_similarity: int,
    ) -> Lead | None:
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        async with self.sessions() as session:
            exact = await session.scalar(
                select(Lead)
                .options(selectinload(Lead.sources))
                .where(Lead.fingerprint == fingerprint)
            )
            if exact:
                return exact

            result = await session.scalars(
                select(Lead)
                .options(selectinload(Lead.sources))
                .where(Lead.created_at >= cutoff)
                .order_by(Lead.created_at.desc())
                .limit(300)
            )
            for candidate in result:
                if similarity(candidate.normalized_text, normalized_text) >= minimum_similarity:
                    return candidate
        return None

    async def create_lead(self, lead: Lead, source: LeadSource) -> Lead:
        async with self.sessions() as session:
            lead.sources.append(source)
            session.add(lead)
            await session.commit()
            await session.refresh(lead, attribute_names=["sources"])
            return lead

    async def add_source(self, lead_id: int, source: LeadSource) -> bool:
        async with self.sessions() as session:
            exists = await session.scalar(
                select(LeadSource.id).where(
                    LeadSource.chat_id == source.chat_id,
                    LeadSource.message_id == source.message_id,
                )
            )
            if exists:
                return False
            source.lead_id = lead_id
            session.add(source)
            await session.commit()
            return True

    async def get_lead(self, lead_id: int) -> Lead | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(Lead).options(selectinload(Lead.sources)).where(Lead.id == lead_id)
            )

    async def set_status(self, lead_id: int, status: LeadStatus) -> bool:
        async with self.sessions() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                return False
            lead.status = status.value
            await session.commit()
            return True

    async def stats_today(self) -> dict[str, int]:
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.sessions() as session:
            total = await session.scalar(
                select(func.count(Lead.id)).where(Lead.created_at >= today)
            )
            contacted = await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.created_at >= today,
                    Lead.status == LeadStatus.CONTACTED.value,
                )
            )
            rejected = await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.created_at >= today,
                    Lead.status.in_([LeadStatus.NOT_RELEVANT.value, LeadStatus.SPAM.value]),
                )
            )
        return {
            "total": int(total or 0),
            "contacted": int(contacted or 0),
            "rejected": int(rejected or 0),
        }

from __future__ import annotations

import asyncio
import hmac
from contextlib import suppress
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import Settings
from app.ingestion import LeadProcessor, ProcessingStatus
from app.notifier import Notifier
from app.tgstat import parse_tgstat_event

logger = structlog.get_logger(__name__)


class TGStatWebhookServer:
    def __init__(
        self,
        settings: Settings,
        processor: LeadProcessor,
        notifier: Notifier,
    ) -> None:
        self.settings = settings
        self.processor = processor
        self.notifier = notifier
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=settings.tgstat_queue_size
        )
        self.app = FastAPI(title="ParcerTG webhook", docs_url=None, redoc_url=None)
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=settings.web_host,
                port=settings.web_port,
                log_config=None,
                access_log=False,
            )
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.get("/health")
        async def health() -> dict[str, object]:
            return {
                "status": "ok",
                "providers": sorted(self.settings.parsed_source_providers),
                "tgstat_queue_size": self.queue.qsize(),
            }

        @self.app.post("/webhooks/tgstat/{secret}")
        async def tgstat_callback(secret: str, request: Request):
            expected = self.settings.tgstat_webhook_secret or ""
            if not expected or not hmac.compare_digest(secret, expected):
                raise HTTPException(status_code=404, detail="Not found")

            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}

            # During callback URL verification TGStat expects this exact string.
            if "event_type" not in payload:
                if self.settings.tgstat_verify_code:
                    return PlainTextResponse(self.settings.tgstat_verify_code)
                return PlainTextResponse(
                    "TGSTAT_VERIFY_CODE is not configured",
                    status_code=503,
                )

            try:
                self.queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.error("tgstat_queue_full", queue_size=self.queue.qsize())
                return JSONResponse(
                    status_code=503,
                    content={"status": "retry", "reason": "queue_full"},
                )
            return JSONResponse(status_code=202, content={"status": "accepted"})

    async def _worker(self) -> None:
        while True:
            payload = await self.queue.get()
            try:
                incoming = parse_tgstat_event(payload)
                if incoming is None:
                    logger.info(
                        "tgstat_event_ignored",
                        event_type=payload.get("event_type"),
                    )
                    continue
                result = await self.processor.process(incoming)
                if (
                    result.status is ProcessingStatus.ACCEPTED
                    and result.lead is not None
                ):
                    await self.notifier.send_lead(result.lead)
            except Exception:
                logger.exception(
                    "tgstat_event_processing_failed",
                    event_id=payload.get("event_id"),
                )
            finally:
                self.queue.task_done()

    async def run(self) -> None:
        self._worker_task = asyncio.create_task(
            self._worker(),
            name="tgstat-event-worker",
        )
        logger.info(
            "tgstat_webhook_started",
            host=self.settings.web_host,
            port=self.settings.web_port,
            path="/webhooks/tgstat/<secret>",
        )
        try:
            await self.server.serve()
        finally:
            if self._worker_task:
                self._worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._worker_task

    async def close(self) -> None:
        self.server.should_exit = True

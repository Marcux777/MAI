from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any, Callable, Optional

from sqlalchemy import func, select

from mai.core.config import get_settings
from mai.core.logging import logger
from mai.db import models
from mai.db.session import session_scope
from mai.ingest.pipeline import SUPPORTED_EXTENSIONS, build_providers, ingest_file, scan_directory
from mai.organizer.service import apply_manifest, rollback_manifest

TASK_KIND_IMPORT_SCAN = "import_scan"
TASK_KIND_ORGANIZE_APPLY = "organize_apply"
TASK_KIND_ORGANIZE_ROLLBACK = "organize_rollback"

_TASK_LABELS = {
    TASK_KIND_IMPORT_SCAN: "Scan de importacao",
    TASK_KIND_ORGANIZE_APPLY: "Organizar (aplicar)",
    TASK_KIND_ORGANIZE_ROLLBACK: "Organizar (rollback)",
}


@dataclass
class TaskStats:
    pending: int
    running: int
    total: int
    last_finished_at: Optional[datetime]


class TaskReporter:
    def __init__(self, task_id: int, queue: "TaskQueue", min_interval: float = 0.5) -> None:
        self.task_id = task_id
        self._queue = queue
        self._min_interval = min_interval
        self._last_flush = 0.0
        self._result: dict[str, Any] = {}

    def update_progress(
        self,
        current: int,
        total: int,
        message: str | None = None,
        extra: dict[str, Any] | None = None,
        force: bool = False,
    ) -> None:
        percent = 0.0 if total <= 0 else (current / total) * 100.0
        progress = {
            "current": int(current),
            "total": int(total),
            "percent": round(percent, 2),
        }
        if message:
            progress["message"] = message
        if extra:
            progress["extra"] = extra
        self._result["progress"] = progress
        self._flush(force=force)

    def set_summary(self, summary: dict[str, Any]) -> None:
        self._result["summary"] = summary
        self._flush(force=True)

    def set_error(self, error: str) -> None:
        self._result["error"] = error
        self._flush(force=True)

    def set_result(self, result: dict[str, Any]) -> None:
        self._result.update(result)
        self._flush(force=True)

    def _flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_flush) < self._min_interval:
            return
        self._last_flush = now
        self._queue.update_result(self.task_id, self._result)


@dataclass
class TaskContext:
    task_id: int
    payload: dict[str, Any]
    reporter: TaskReporter


TaskHandler = Callable[[TaskContext], dict[str, Any] | None]


@dataclass
class TaskDefinition:
    kind: str
    label: str
    handler: TaskHandler


def _collect_scan_files(paths: list[Path]) -> tuple[list[Path], int]:
    files: list[Path] = []
    skipped = 0
    for path in paths:
        if path.is_dir():
            files.extend(scan_directory(path))
            continue
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
        else:
            skipped += 1
    seen: set[str] = set()
    unique: list[Path] = []
    for item in files:
        resolved = str(item.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(item)
    return unique, skipped


def _handle_import_scan(ctx: TaskContext) -> dict[str, Any]:
    raw_paths = ctx.payload.get("paths") or []
    paths: list[Path] = []
    for item in raw_paths:
        path = Path(item).expanduser().resolve()
        if not path.exists():
            logger.warning("Caminho nao encontrado no scan: %s", path)
            continue
        paths.append(path)
    files, skipped = _collect_scan_files(paths)
    total = len(files)
    ctx.reporter.update_progress(0, total, "Scan iniciado", force=True)

    settings = get_settings()
    providers = build_providers(settings.google_books_key)
    ok = 0
    failed = 0

    for idx, file_path in enumerate(files, start=1):
        ctx.reporter.update_progress(idx - 1, total, f"Iniciando {file_path.name}")
        try:
            with session_scope() as session:
                ingest_file(session, file_path, providers)
            ok += 1
        except Exception as exc:  # pragma: no cover - log and continue
            failed += 1
            logger.exception("Falha ao ingerir %s: %s", file_path, exc)
        ctx.reporter.update_progress(idx, total, f"Processado {file_path.name}")

    summary = {"total": total, "ok": ok, "failed": failed, "skipped": skipped}
    ctx.reporter.set_summary(summary)
    return {"summary": summary, "paths": [str(p) for p in paths]}


def _handle_organize_apply(ctx: TaskContext) -> dict[str, Any]:
    manifest_id = int(ctx.payload.get("manifest_id") or 0)
    statuses = ctx.payload.get("statuses")
    settings = get_settings()

    def progress_cb(current: int, total: int, message: str) -> None:
        ctx.reporter.update_progress(current, total, message)

    with session_scope() as session:
        summary = apply_manifest(
            session,
            manifest_id,
            settings,
            statuses=statuses,
            progress_cb=progress_cb,
        )

    ctx.reporter.set_summary(summary)
    return {"manifest_id": manifest_id, "summary": summary}


def _handle_organize_rollback(ctx: TaskContext) -> dict[str, Any]:
    manifest_id = int(ctx.payload.get("manifest_id") or 0)
    settings = get_settings()

    def progress_cb(current: int, total: int, message: str) -> None:
        ctx.reporter.update_progress(current, total, message)

    with session_scope() as session:
        summary = rollback_manifest(session, manifest_id, settings, progress_cb=progress_cb)

    ctx.reporter.set_summary(summary)
    return {"manifest_id": manifest_id, "summary": summary}


_TASK_DEFINITIONS: dict[str, TaskDefinition] = {
    TASK_KIND_IMPORT_SCAN: TaskDefinition(
        kind=TASK_KIND_IMPORT_SCAN,
        label=_TASK_LABELS[TASK_KIND_IMPORT_SCAN],
        handler=_handle_import_scan,
    ),
    TASK_KIND_ORGANIZE_APPLY: TaskDefinition(
        kind=TASK_KIND_ORGANIZE_APPLY,
        label=_TASK_LABELS[TASK_KIND_ORGANIZE_APPLY],
        handler=_handle_organize_apply,
    ),
    TASK_KIND_ORGANIZE_ROLLBACK: TaskDefinition(
        kind=TASK_KIND_ORGANIZE_ROLLBACK,
        label=_TASK_LABELS[TASK_KIND_ORGANIZE_ROLLBACK],
        handler=_handle_organize_rollback,
    ),
}


class TaskQueue:
    def __init__(self, worker_count: int = 1) -> None:
        self._queue: Queue[Optional[int]] = Queue()
        self._stop_event = Event()
        self._workers: list[Thread] = []
        self._lock = Lock()
        self._started = False
        self._worker_count = max(1, worker_count)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._stop_event.clear()
            self._restore_pending_tasks()
            self._workers = []
            for idx in range(self._worker_count):
                thread = Thread(
                    target=self._worker_loop,
                    name=f"mai-task-worker-{idx + 1}",
                    daemon=True,
                )
                thread.start()
                self._workers.append(thread)
            self._started = True
            logger.info("Task queue iniciada com %s worker(s).", self._worker_count)

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop_event.set()
            for _ in self._workers:
                self._queue.put(None)
        for thread in self._workers:
            thread.join(timeout=5)
        self._workers = []
        self._started = False
        logger.info("Task queue encerrada.")

    def enqueue(self, kind: str, payload: dict[str, Any]) -> int:
        if kind not in _TASK_DEFINITIONS:
            raise ValueError(f"Tarefa desconhecida: {kind}")
        if not self._started:
            self.start()
        payload_json = json.dumps(payload, ensure_ascii=True)
        with session_scope() as session:
            task = models.Task(kind=kind, payload_json=payload_json, status="pending")
            session.add(task)
            session.flush()
            task_id = task.id
        self._queue.put(task_id)
        logger.info("Task enfileirada id=%s kind=%s", task_id, kind)
        return task_id

    def update_result(self, task_id: int, result: dict[str, Any]) -> None:
        payload_json = json.dumps(result, ensure_ascii=True)
        with session_scope() as session:
            task = session.get(models.Task, task_id)
            if not task:
                return
            task.result_json = payload_json

    def get_stats(self) -> TaskStats:
        with session_scope() as session:
            total = session.scalar(select(func.count()).select_from(models.Task)) or 0
            pending = (
                session.scalar(
                    select(func.count()).select_from(models.Task).where(models.Task.status == "pending")
                )
                or 0
            )
            running = (
                session.scalar(
                    select(func.count()).select_from(models.Task).where(models.Task.status == "running")
                )
                or 0
            )
            last_finished = session.scalar(select(func.max(models.Task.finished_at)))
        return TaskStats(pending=pending, running=running, total=total, last_finished_at=last_finished)

    @staticmethod
    def get_label(kind: str) -> str:
        return _TASK_LABELS.get(kind, kind)

    def _restore_pending_tasks(self) -> None:
        with session_scope() as session:
            running = session.scalars(
                select(models.Task).where(models.Task.status == "running")
            ).all()
            for task in running:
                task.status = "pending"
                task.started_at = None
                task.finished_at = None
                task.result_json = None
            pending = session.scalars(
                select(models.Task)
                .where(models.Task.status == "pending")
                .order_by(models.Task.id)
            ).all()
            session.flush()
            pending_ids = [task.id for task in pending]

        for task_id in pending_ids:
            self._queue.put(task_id)

        if pending_ids:
            logger.info("Reenfileiradas %s task(s) pendentes.", len(pending_ids))

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            task_id = self._queue.get()
            if task_id is None:
                break
            self._process_task(task_id)

    def _process_task(self, task_id: int) -> None:
        with session_scope() as session:
            task = session.get(models.Task, task_id)
            if not task:
                return
            if task.status != "pending":
                return
            task.status = "running"
            task.started_at = datetime.utcnow()
            payload = _safe_json_loads(task.payload_json)
            task_kind = task.kind
            session.flush()

        definition = _TASK_DEFINITIONS.get(task_kind)
        reporter = TaskReporter(task_id, self)
        if not definition:
            reporter.set_error("Tipo de tarefa desconhecido.")
            self._finish_task(task_id, status="failed")
            return

        logger.info("Executando task id=%s kind=%s", task_id, task_kind)
        try:
            context = TaskContext(task_id=task_id, payload=payload or {}, reporter=reporter)
            result = definition.handler(context)
            if result is not None:
                reporter.set_result(result)
            self._finish_task(task_id, status="done")
            logger.info("Task concluida id=%s kind=%s", task_id, task_kind)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Task falhou id=%s kind=%s: %s", task_id, task_kind, exc)
            reporter.set_error(str(exc))
            self._finish_task(task_id, status="failed")

    def _finish_task(self, task_id: int, status: str) -> None:
        with session_scope() as session:
            task = session.get(models.Task, task_id)
            if not task:
                return
            task.status = status
            task.finished_at = datetime.utcnow()


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


_QUEUE: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _QUEUE
    if _QUEUE is None:
        settings = get_settings()
        workers = int(getattr(settings, "task_workers", 1) or 1)
        _QUEUE = TaskQueue(worker_count=workers)
    return _QUEUE

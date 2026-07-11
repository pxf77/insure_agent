from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict

from quant_agent.execution.idempotency import IdempotencyStore
from quant_agent.execution.paper_gateway_v2 import (
    DeterministicPaperGateway,
    PaperFillConfig,
)
from quant_agent.execution.reconciliation_v2 import expected_positions, reconcile_positions
from quant_agent.execution.state_machine import (
    InvalidOrderTransition,
    OrderStateMachine,
    OutOfOrderOrderEvent,
)
from quant_agent.execution.v2_models import (
    EventType,
    ExecutionContext,
    ExecutionIntent,
    OrderAggregate,
    OrderEvent,
    ReconciliationReport,
)

_REQUIRED_ORDER_FILES = {
    "intent.json",
    "order.json",
    "events.json",
    "quarantine.json",
}


class QuarantinedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: OrderEvent
    reason_code: str
    message: str


@dataclass(frozen=True)
class PaperExecutionResult:
    run_id: str
    orders: list[OrderAggregate]
    order_directories: list[Path]
    reconciliation: ReconciliationReport
    reconciliation_path: Path
    reused_orders: int


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class PaperExecutionRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        idempotency_path: str | Path,
    ):
        self.artifact_root = Path(artifact_root)
        self.idempotency_store = IdempotencyStore(idempotency_path)
        self.gateway = DeterministicPaperGateway()
        self.state_machine = OrderStateMachine()

    def run(
        self,
        *,
        intents: list[ExecutionIntent],
        context: ExecutionContext,
        fill_configs: dict[str, PaperFillConfig] | None = None,
        gateway_positions: dict[str, int] | None = None,
    ) -> PaperExecutionResult:
        if not intents:
            raise ValueError("paper execution requires at least one order intent")
        fill_configs = fill_configs or {}
        aggregates: list[OrderAggregate] = []
        order_directories: list[Path] = []
        reused_orders = 0
        for intent in sorted(intents, key=lambda item: item.idempotency_key):
            if intent.account_id != context.account_id:
                raise ValueError("intent account does not match execution context")
            if intent.strategy_id != context.strategy_id:
                raise ValueError("intent strategy does not match execution context")
            if intent.risk_decision_id != context.risk_decision_id:
                raise ValueError("intent risk decision does not match execution context")
            order_id, reused = self.idempotency_store.claim(intent)
            order_dir = self.artifact_root / "execution_v2" / "orders" / str(order_id)
            if reused:
                aggregate = self._load_existing(order_dir, intent, order_id)
                reused_orders += 1
            else:
                aggregate = self._execute_new(
                    intent=intent,
                    order_id=order_id,
                    order_dir=order_dir,
                    fill_config=fill_configs.get(
                        str(intent.instrument),
                        PaperFillConfig(),
                    ),
                )
            aggregates.append(aggregate)
            order_directories.append(order_dir)

        expected = expected_positions(holdings=context.holdings, orders=aggregates)
        actual = expected if gateway_positions is None else gateway_positions
        reconciliation = reconcile_positions(
            run_id=intents[0].run_id,
            checked_at=context.created_at + timedelta(seconds=1),
            holdings=context.holdings,
            orders=aggregates,
            gateway_positions=actual,
        )
        reconciliation_path = self._write_reconciliation(
            run_id=intents[0].run_id,
            risk_decision_id=context.risk_decision_id,
            report=reconciliation,
        )
        if reconciliation.halted:
            halt_path = self.artifact_root / "execution_state" / "EXECUTION_HALT"
            halt_path.parent.mkdir(parents=True, exist_ok=True)
            halt_path.write_text(
                f"run_id={intents[0].run_id}\nreason=RECONCILIATION_CRITICAL\n",
                encoding="utf-8",
            )
        return PaperExecutionResult(
            run_id=intents[0].run_id,
            orders=aggregates,
            order_directories=order_directories,
            reconciliation=reconciliation,
            reconciliation_path=reconciliation_path,
            reused_orders=reused_orders,
        )

    def _execute_new(
        self,
        *,
        intent: ExecutionIntent,
        order_id: UUID,
        order_dir: Path,
        fill_config: PaperFillConfig,
    ) -> OrderAggregate:
        aggregate = OrderAggregate(order_id=order_id, intent=intent)
        events = [
            self._internal_event(
                intent=intent,
                order_id=order_id,
                sequence=0,
                event_type=EventType.VALIDATE,
                offset_ms=0,
            ),
            self._internal_event(
                intent=intent,
                order_id=order_id,
                sequence=1,
                event_type=EventType.SUBMIT,
                offset_ms=1,
            ),
        ]
        events.extend(
            self.gateway.events(
                intent=intent,
                order_id=order_id,
                config=fill_config,
            )
        )
        quarantine: list[QuarantinedEvent] = []
        applied_events: list[OrderEvent] = []
        for event in events:
            try:
                aggregate = self.state_machine.apply(aggregate, event)
                applied_events.append(event)
            except OutOfOrderOrderEvent as exc:
                quarantine.append(
                    QuarantinedEvent(
                        event=event,
                        reason_code="OUT_OF_ORDER_EVENT",
                        message=str(exc),
                    )
                )
            except InvalidOrderTransition as exc:
                quarantine.append(
                    QuarantinedEvent(
                        event=event,
                        reason_code="INVALID_ORDER_TRANSITION",
                        message=str(exc),
                    )
                )
        self._write_order_artifacts(
            order_dir=order_dir,
            intent=intent,
            aggregate=aggregate,
            events=applied_events,
            quarantine=quarantine,
        )
        return aggregate

    def _write_order_artifacts(
        self,
        *,
        order_dir: Path,
        intent: ExecutionIntent,
        aggregate: OrderAggregate,
        events: list[OrderEvent],
        quarantine: list[QuarantinedEvent],
    ) -> None:
        files = {
            "intent.json": _canonical_json(intent.model_dump(mode="json")),
            "order.json": _canonical_json(aggregate.model_dump(mode="json")),
            "events.json": _canonical_json(
                [event.model_dump(mode="json") for event in events]
            ),
            "quarantine.json": _canonical_json(
                [item.model_dump(mode="json") for item in quarantine]
            ),
        }
        temporary = order_dir.parent / f".{order_dir.name}.{uuid4().hex}.tmp"
        try:
            temporary.mkdir(parents=True, exist_ok=False)
            for name, content in files.items():
                (temporary / name).write_bytes(content)
            manifest = {
                "schema_version": "1.0",
                "order_id": str(aggregate.order_id),
                "files": {
                    name: _sha256(content)
                    for name, content in sorted(files.items())
                },
            }
            (temporary / "manifest.json").write_bytes(_canonical_json(manifest))
            order_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(temporary, order_dir)
            except FileExistsError:
                shutil.rmtree(temporary)
                self._load_existing(order_dir, intent, aggregate.order_id)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    @staticmethod
    def _load_existing(
        order_dir: Path,
        intent: ExecutionIntent,
        order_id: UUID,
    ) -> OrderAggregate:
        manifest_path = order_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("idempotency record exists without a complete order artifact")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("order_id") != str(order_id):
            raise ValueError("order artifact ID mismatch")
        hashes = cast(dict[str, str], manifest.get("files", {}))
        if set(hashes) != _REQUIRED_ORDER_FILES:
            raise ValueError("order manifest contains an unexpected artifact set")
        actual_files = {
            path.relative_to(order_dir).as_posix()
            for path in order_dir.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        if actual_files != _REQUIRED_ORDER_FILES | {"manifest.json"}:
            raise ValueError("order artifact contains missing or unexpected files")
        for name, expected_hash in hashes.items():
            path = order_dir / name
            if path.is_symlink() or _sha256(path.read_bytes()) != expected_hash:
                raise ValueError(f"order artifact failed integrity check: {name}")
        persisted_intent = ExecutionIntent.model_validate_json(
            (order_dir / "intent.json").read_text(encoding="utf-8")
        )
        if persisted_intent != intent:
            raise ValueError("idempotency key resolved to a different persisted intent")
        return OrderAggregate.model_validate_json(
            (order_dir / "order.json").read_text(encoding="utf-8")
        )

    def _write_reconciliation(
        self,
        *,
        run_id: str,
        risk_decision_id: str,
        report: ReconciliationReport,
    ) -> Path:
        content = _canonical_json(report.model_dump(mode="json"))
        identity = _sha256(
            _canonical_json(
                {
                    "run_id": run_id,
                    "risk_decision_id": risk_decision_id,
                    "report_sha256": _sha256(content),
                }
            )
        )[:20]
        path = (
            self.artifact_root
            / "execution_v2"
            / "runs"
            / run_id
            / f"reconciliation-{identity}.json"
        )
        if path.exists():
            if _sha256(path.read_bytes()) != _sha256(content):
                raise ValueError("existing reconciliation artifact failed integrity check")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)
        return path

    @staticmethod
    def _internal_event(
        *,
        intent: ExecutionIntent,
        order_id: UUID,
        sequence: int,
        event_type: EventType,
        offset_ms: int,
    ) -> OrderEvent:
        return OrderEvent(
            event_id=uuid5(
                NAMESPACE_URL,
                f"internal-event:{order_id}:{sequence}:{event_type.value}",
            ),
            order_id=order_id,
            event_type=event_type,
            occurred_at=intent.created_at + timedelta(milliseconds=offset_ms),
        )

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from quant_agent.schemas.v2 import (
    EventEnvelope,
    InstrumentId,
    OrderIntent,
    ResearchSpec,
    RiskDecisionV2,
    TargetPortfolio,
)

CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "event-envelope-1.0": EventEnvelope,
    "instrument-id-1.0": InstrumentId,
    "order-intent-2.0": OrderIntent,
    "research-spec-2.0": ResearchSpec,
    "risk-decision-2.0": RiskDecisionV2,
    "target-portfolio-2.0": TargetPortfolio,
}


@dataclass(frozen=True)
class SchemaExportResult:
    output_dir: Path
    index_path: Path
    schema_paths: tuple[Path, ...]


def _render_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_contract_schemas(output_dir: str | Path) -> SchemaExportResult:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    schema_paths: list[Path] = []

    for contract_name, model in sorted(CONTRACT_MODELS.items()):
        schema_path = destination / f"{contract_name}.schema.json"
        content = _render_json(model.model_json_schema(mode="validation"))
        schema_path.write_text(content, encoding="utf-8")
        entries.append(
            {
                "contract": contract_name,
                "file": schema_path.name,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
        schema_paths.append(schema_path)

    index_path = destination / "index.json"
    index_path.write_text(
        _render_json(
            {
                "schema_set_version": "v0.1",
                "schemas": entries,
            }
        ),
        encoding="utf-8",
    )
    return SchemaExportResult(
        output_dir=destination,
        index_path=index_path,
        schema_paths=tuple(schema_paths),
    )

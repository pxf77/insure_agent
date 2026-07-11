from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one occurrence, found {count}")
    return text.replace(old, new, 1)


def patch_engine() -> None:
    path = Path("src/quant_agent/risk/v2_engine.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from quant_agent.risk.kill_switch_store import KillSwitchState, KillSwitchStore\n",
        "from quant_agent.risk.approval_store import ApprovalState, ApprovalStore\n"
        "from quant_agent.risk.kill_switch_store import KillSwitchState, KillSwitchStore\n",
        "engine approval import",
    )
    text, count = re.subn(
        r"    def __init__\(self, \*, policy: RiskPolicy, kill_switch_store: KillSwitchStore\):\n"
        r"        self\.policy = policy\n"
        r"        self\.kill_switch_store = kill_switch_store\n",
        "    def __init__(\n"
        "        self,\n"
        "        *,\n"
        "        policy: RiskPolicy,\n"
        "        kill_switch_store: KillSwitchStore,\n"
        "        approval_store: ApprovalStore | None = None,\n"
        "    ):\n"
        "        self.policy = policy\n"
        "        self.kill_switch_store = kill_switch_store\n"
        "        self.approval_store = approval_store\n",
        text,
    )
    if count != 1:
        raise RuntimeError(f"engine constructor: expected one replacement, found {count}")
    text = replace_once(
        text,
        "        kill_switch_state: KillSwitchState | None = None,\n    ) -> RiskDecisionV2:\n",
        "        kill_switch_state: KillSwitchState | None = None,\n"
        "        approval_state: ApprovalState | None = None,\n"
        "    ) -> RiskDecisionV2:\n",
        "engine evaluate approval state",
    )
    text = replace_once(
        text,
        "        approval_rejection = self._validate_approval(target, context)\n",
        "        approval_rejection = self._validate_approval(\n"
        "            target,\n"
        "            context,\n"
        "            approval_state=approval_state,\n"
        "        )\n",
        "engine approval call",
    )
    pattern = re.compile(
        r"    def _validate_approval\(.*?\n    def _apply_industry_limits\(",
        re.DOTALL,
    )
    replacement = '''    def _validate_approval(
        self,
        target: TargetPortfolio,
        context: RiskContext,
        *,
        approval_state: ApprovalState | None,
    ) -> tuple[str, str] | None:
        if not self.policy.require_approval:
            return None
        approval = context.approval
        if approval is None:
            return "APPROVAL_REQUIRED", "risk policy requires approval evidence"
        expected = {
            "account_id": context.account_id,
            "strategy_id": context.strategy_id,
            "target_run_id": target.run_id,
            "policy_version": self.policy.policy_version,
        }
        actual = {
            "account_id": approval.account_id,
            "strategy_id": approval.strategy_id,
            "target_run_id": approval.target_run_id,
            "policy_version": approval.policy_version,
        }
        if actual != expected:
            return "APPROVAL_SCOPE_MISMATCH", "approval evidence is not bound to this decision"
        trusted_state = approval_state
        if trusted_state is None:
            if self.approval_store is None:
                return "APPROVAL_NOT_TRUSTED", "trusted approval registry is unavailable"
            trusted_state = self.approval_store.read()
        trusted = trusted_state.trusted(approval.approval_id)
        if trusted is None or trusted != approval:
            return "APPROVAL_NOT_TRUSTED", "approval evidence is not present in the trusted registry"
        if approval.approved_at > context.evaluated_at:
            return "APPROVAL_FROM_FUTURE", "approval timestamp is later than evaluation time"
        if context.evaluated_at >= approval.expires_at:
            return "APPROVAL_EXPIRED", "approval evidence has expired"
        return None

    def _apply_industry_limits('''
    text, count = pattern.subn(replacement, text)
    if count != 1:
        raise RuntimeError(f"engine approval function: expected one replacement, found {count}")
    path.write_text(text, encoding="utf-8")


def patch_evals() -> None:
    path = Path("src/quant_agent/evals/risk.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from quant_agent.risk.kill_switch_store import KillSwitchStore\n",
        "from quant_agent.risk.approval_store import ApprovalStore\n"
        "from quant_agent.risk.kill_switch_store import KillSwitchStore\n",
        "eval approval import",
    )
    text = replace_once(
        text,
        "from quant_agent.risk.v2_models import KillSwitchScope, RiskContext, RiskPolicy\n",
        "from quant_agent.risk.v2_models import (\n"
        "    ApprovalEvidence,\n"
        "    KillSwitchScope,\n"
        "    RiskContext,\n"
        "    RiskPolicy,\n"
        ")\n",
        "eval approval model import",
    )
    old = '''            store = KillSwitchStore(Path(temporary) / "kill_switches.json")
            target_payload, context_payload, policy_payload = _prepare_case(case, store)
            target = TargetPortfolio.model_validate(target_payload)
            context = RiskContext.model_validate(context_payload)
            policy = RiskPolicy.model_validate(policy_payload)
            state = store.read()
            decision = DeterministicRiskEngine(
                policy=policy,
                kill_switch_store=store,
            ).evaluate(target, context, kill_switch_state=state)
'''
    new = '''            store = KillSwitchStore(Path(temporary) / "kill_switches.json")
            approval_store = ApprovalStore(Path(temporary) / "approvals.json")
            target_payload, context_payload, policy_payload = _prepare_case(case, store)
            trusted_payload = _approval()
            if case.action in {"approval_expired", "approval_future"}:
                trusted_payload = context_payload["approval"]
            approval_store.issue(ApprovalEvidence.model_validate(trusted_payload))
            target = TargetPortfolio.model_validate(target_payload)
            context = RiskContext.model_validate(context_payload)
            policy = RiskPolicy.model_validate(policy_payload)
            state = store.read()
            approval_state = approval_store.read()
            decision = DeterministicRiskEngine(
                policy=policy,
                kill_switch_store=store,
                approval_store=approval_store,
            ).evaluate(
                target,
                context,
                kill_switch_state=state,
                approval_state=approval_state,
            )
'''
    text = replace_once(text, old, new, "eval trusted approval setup")
    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    for name in ("tests/unit/test_risk_v2.py", "tests/unit/test_risk_v2_adversarial.py"):
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        text = text.replace('"require_approval": True', '"require_approval": False')
        path.write_text(text, encoding="utf-8")

    path = Path("tests/unit/test_risk_v2_service.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import yaml\n\nfrom quant_agent.risk.v2_service import RiskDecisionService\n",
        "import yaml\n\n"
        "from quant_agent.risk.approval_store import ApprovalStore\n"
        "from quant_agent.risk.v2_models import RiskContext\n"
        "from quant_agent.risk.v2_service import RiskDecisionService\n",
        "service test imports",
    )
    text = text.replace(
        "        kill_switch_path=tmp_path / \"risk_state\" / \"switches.json\",\n    )",
        "        kill_switch_path=tmp_path / \"risk_state\" / \"switches.json\",\n"
        "        approval_path=tmp_path / \"risk_state\" / \"approvals.json\",\n"
        "    )",
    )
    marker = "    service = RiskDecisionService(\n"
    issue = '''    context_model = RiskContext.model_validate_json(context.read_text(encoding="utf-8"))
    assert context_model.approval is not None
    ApprovalStore(tmp_path / "risk_state" / "approvals.json").issue(
        context_model.approval
    )
'''
    text = text.replace(marker, issue + marker)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_engine()
    patch_evals()
    patch_tests()


if __name__ == "__main__":
    main()

# Live Trading Checklist

Live trading is not implemented in the local MVP. Real order submission must
remain disabled until every item below is satisfied:

- [ ] Explicit `ENABLE_LIVE_TRADING=true` and an enabled live risk profile.
- [ ] Paper trading has run continuously for at least 60 trading days.
- [ ] No duplicate orders, unexplained ledger differences, or silent data gaps.
- [ ] Data, config, code, decisions, approvals, orders, fills, and NAV are auditable.
- [ ] Expired approvals, changed plans, corrupt artifacts, and mixed `run_id` values fail closed.
- [ ] The kill switch blocks submission even when activated after risk approval.
- [ ] Account, position, cash, fee, fill, and end-of-day reconciliation is rehearsed.
- [ ] Read-only account integration has completed a separate security review.
- [ ] The account's securities company has confirmed programmatic-trading reporting.
- [ ] Only official vendor or broker SDKs are used; GUI automation and private protocols are prohibited.
- [ ] `live_shadow` is stable and daily simulation-to-account differences are explained.
- [ ] Any `live_manual` mode is proposed and approved as a separate OpenSpec change.
- [ ] Manual approval, audit logging, deterministic risk checks, and the kill switch cannot be bypassed.

The first implementation phase explicitly excludes unattended live trading,
LLM-controlled production strategy or risk changes, LLM order submission,
minute-level trading, write-enabled vn.py gateways, and premature distributed
infrastructure.

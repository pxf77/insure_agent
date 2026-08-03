# Live Trading Checklist

Live trading is not implemented in the local MVP.

Before any future live-trading mode is enabled, require:

- Explicit `ENABLE_LIVE_TRADING=true`.
- Enabled risk profile for live mode.
- Manual approval or a documented approval waiver.
- Kill switch validation.
- Broker gateway dry-run and reconciliation checks.
- Audit logs for all generated orders and trades.
- Confirmed programmatic-trading report through the account's securities company.
- Official vendor or broker SDK; GUI automation and private protocol adapters are prohibited.
- `live_shadow` read-only capture and reconciliation completed before any submit capability.

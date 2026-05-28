# Live Trading Checklist

Live trading is not implemented in the local MVP.

Before any future live-trading mode is enabled, require:

- Explicit `ENABLE_LIVE_TRADING=true`.
- Enabled risk profile for live mode.
- Manual approval or a documented approval waiver.
- Kill switch validation.
- Broker gateway dry-run and reconciliation checks.
- Audit logs for all generated orders and trades.

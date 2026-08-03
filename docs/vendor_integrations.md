# Vendor Integrations

The project supports official Eastmoney Choice and Tonghuashun iFinD market-data
interfaces. Real-money order submission remains disabled.

## Eastmoney Choice

1. Download and activate the official `EmQuantAPI` Python SDK outside this repository.
2. Confirm `python -c "from EmQuantAPI import c"` succeeds in the project environment.
3. Keep the generated activation token and vendor libraries outside Git.
4. Build an immutable daily-bar snapshot:

```bash
quant-agent data snapshot \
  --provider choice \
  --symbols 600519.SH,000001.SZ \
  --batch-size 50 \
  --lookback-days 365 \
  --as-of 2026-05-22T16:00:00+08:00
```

The adapter calls the documented `c.start`, `c.csd`, and `c.stop` functions, uses the
documented non-pandas nested response by default, batches large symbol sets, and spaces
batch requests by 100 milliseconds to stay below the documented 700 sequence requests per
minute. It defaults to non-forced login and disables the SDK login-information log. Optional
non-secret SDK arguments can be set through `CHOICE_LOGIN_OPTIONS` and
`CHOICE_CSD_OPTIONS`. Do not place an account name, password, token, or SDK activation
file in repository configuration.

A demo-only `Demo_Python.zip` archive contains example scripts but is not an installable
SDK. A runnable installation requires the complete official `EmQuantAPI_Python.zip`
distribution, including
`installEmQuantAPI.py`, `libs`, and activation support.

Official references:

- <https://quantapi.eastmoney.com/Exp/Search?from=web>
- <https://quantapi.eastmoney.com/Upload/EMQuantAPI_Python.html>

## Tonghuashun iFinD

Set the official HTTP access token only in the process environment:

```bash
export IFIND_ACCESS_TOKEN="<redacted>"
quant-agent data snapshot \
  --provider ifind \
  --symbols 600519.SH,000001.SZ \
  --batch-size 50 \
  --lookback-days 365 \
  --as-of 2026-05-22T16:00:00+08:00
```

The adapter uses the official history quotation endpoint, batches symbols, spaces batch
requests by 110 milliseconds, enforces timeouts, retries transient transport failures,
validates the vendor error code, and never prints the access token. Reduce `--batch-size`
if the subscribed product imposes a lower per-request symbol limit.

Official reference: <https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/example.html>

## Live Shadow

An official broker or vendor sidecar may export account truth in the validated JSON format
shown in `configs/execution/shadow_snapshot.example.json`. Import it with:

```bash
quant-agent execution shadow \
  --snapshot configs/execution/shadow_snapshot.example.json \
  --config configs/env/live_shadow.yaml
```

The live-shadow gateway is deliberately capability-limited:

- it has no submit-order or cancel-order method;
- `runtime.allow_live_trading` remains false;
- artifacts are content-addressed and immutable;
- artifact directories use owner-only `0700` and files use `0600` permissions on POSIX
  hosts; Windows deployments must apply equivalent owner-only ACLs;
- duplicate positions, orders, and trades are rejected;
- account, position, order, and trade fields are schema validated.

Before an official trading SDK is implemented, require broker authorization, programmatic
trading report confirmation, a dedicated gateway host, reconciliation, idempotency,
short-lived manual approval, and kill-switch drills.

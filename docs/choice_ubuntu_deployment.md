# Choice Ubuntu Deployment

Use a stable Ubuntu host and a dedicated unprivileged service account. Choice activation is
device-bound, so do not activate inside an ephemeral container or CI runner.

## 1. Install the project

Create a fixed application directory and Python environment. The examples assume the
repository is checked out at `/opt/insure-agent` and the service account owns that directory.

```bash
cd /opt/insure-agent
uv venv --python 3.13
uv pip install --python .venv/bin/python -e .
```

## 2. Install the pinned official SDK

The installer downloads Choice Python SDK V2.7.5.0 from the official CDN, verifies its
pinned SHA-256, installs it outside Git, registers it only with the selected Python
environment, and applies owner-only permissions.

```bash
scripts/install_choice_sdk.sh \
  /opt/insure-agent/vendor/choice/2.7.5.0 \
  /opt/insure-agent/.venv/bin/python
```

For an offline host, download `EMQuantAPI_Python.zip` from the official Choice download
center, transfer it through the approved channel, and pass its local path as the third
argument. Never use an archive whose checksum differs from the installer pin.

## 3. Activate on the stable host

### GUI-capable host

Run the official Ubuntu activator as the same service account that will fetch data:

```bash
cd /opt/insure-agent/vendor/choice/2.7.5.0/libs/linux/x64
./loginactivator_ubuntu
```

### Headless host

Bind a phone number to the Choice API account in the official portal. Send `SXDL` to
`9535711`, then enter the phone number in the server terminal without putting it in shell
history:

```bash
read -r -s -p 'Choice phone: ' CHOICE_PHONE
echo
```

The SMS login window is ten minutes. Run the read-only smoke test in that window. A
successful login generates the device-bound `userInfo` file. Afterwards, unset the login
options so normal token login is used:

```bash
CHOICE_LOGIN_OPTIONS="LoginMode=SXDL,PhoneNumber=${CHOICE_PHONE},ForceLogin=0,RecordLoginInfo=0,HTTPTimeout=15" \
  .venv/bin/quant-agent data snapshot \
  --provider choice \
  --symbols 600519.SH \
  --lookback-days 5 \
  --as-of 2026-08-03T16:00:00+08:00

unset CHOICE_PHONE
find /opt/insure-agent/vendor/choice/2.7.5.0 -name userInfo -exec chmod 600 {} \;
```

Do not paste the phone number, account password, or `userInfo` content into chat, logs,
configuration YAML, process arguments, or Git.

## 4. Verify and fetch an analysis snapshot

```bash
.venv/bin/python -c 'from EmQuantAPI import c; print("Choice SDK import: OK")'

.venv/bin/quant-agent data snapshot \
  --provider choice \
  --symbols 600519.SH,000001.SZ \
  --batch-size 50 \
  --lookback-days 365 \
  --as-of 2026-08-03T16:00:00+08:00
```

The command writes an immutable point-in-time snapshot under `artifacts/data/snapshots`.
It does not enable account access, order submission, or cancellation.

## 5. Operational boundary

- Keep `runtime.allow_live_trading=false`.
- Back up neither the activation token nor account data to Git or general-purpose object
  storage.
- Run Choice from one stable device unless the subscription explicitly permits multiple
  simultaneous sessions.
- Rotate the activation after a device change or account password change.
- Run the snapshot command under the same OS account and Python environment used during
  activation.

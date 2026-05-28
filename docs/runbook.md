# Local MVP Runbook

Run the local paper-mode MVP:

```bash
quant-agent init
quant-agent data pull --sample
quant-agent data convert
quant-agent research qlib
quant-agent risk validate
quant-agent paper run
quant-agent report generate
quant-agent latest
```

All outputs are written under `artifacts/`.

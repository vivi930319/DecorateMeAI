## Agent skills

### Issue tracker

Issues and PRDs are tracked as **GitHub issues** in `vivi930319/DecorateMeAI` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles use their **default** label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

**Single-context** — when domain docs exist they live at the repo root: one `CONTEXT.md` + `docs/adr/`. This declares the layout, not that the files are present; they're created lazily by `/domain-modeling` once a term or decision actually gets resolved, so their absence is expected and shouldn't be reported as a gap. See `docs/agents/domain.md`.

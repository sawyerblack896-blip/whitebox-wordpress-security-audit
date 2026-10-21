# Whitebox WordPress audit runtime — public edition

This repository contains the reusable, non-policy runtime from our WordPress
security-audit system. It is deliberately useful on its own: it can acquire a
pinned source tree, run a deployment-supplied long-lived audit Goal, checkpoint
each turn, and support bounded WordPress/Docker reproduction and a read-only
progress dashboard.

The runtime is intentionally policy-neutral. A deployment supplies its own
prompt/schema adapter and its own review process. The public tree does not
contain our target-selection strategy, Wordfence Gate, private prompts, live
queues, findings, credentials, or evidence.

## Included runtime

- `whitebox/providers.py` — provider adapters and structured-result handling;
- `whitebox/source.py` — source acquisition, revision pinning, and safe archive
  extraction;
- `whitebox/audit_goal.py` — one resumable investigation Goal with turn
  checkpoints and a time boundary;
- `whitebox/lab.py` and `whitebox/docker_lab.py` — bounded disposable-lab
  helpers;
- `whitebox/dashboard.py` and `whitebox/dashboard.html` — a read-only status
  view backed by deployment-owned state; and
- `whitebox/quota.py` and `whitebox/util.py` — provider-limit and persistence
  helpers that do not print credentials.

Run the Goal with a deployment-owned JSON prompt/schema file; no operational
prompt is shipped here:

```bash
python -m whitebox.audit_goal \
  --target my-plugin \
  --source /path/to/pinned/source \
  --work /path/to/run-state \
  --prompt-file /private/deployment/prompt.json \
  --seconds 21600
```

## Deliberate boundary

The private repository remains authoritative for target selection, competition
and exclusion signals, current Wordfence scope/bounty rules, qualification
gates, prompts, model routing, target queues, run evidence, reports, logs,
accounts, credentials, and infrastructure paths. Nothing in this public tree
reveals those assets, and this repository is not a copy of Codex Security.

The public lifecycle is therefore simple: pin source, investigate with one
long-lived Goal, preserve source-backed chains, reproduce credible candidates
in a disposable lab with a negative control, then let a deployment-owned human
or policy review decide what is eligible to submit.

## Public CVE index

Only the six CVE records explicitly cleared for public disclosure are listed in
[`docs/wordpress-security-case-studies.md`](docs/wordpress-security-case-studies.md):
CVE-2026-109401, CVE-2026-107645, CVE-2026-107646, CVE-2026-107652,
CVE-2026-103964, and CVE-2026-107754. No unpublished candidate or private
proof-of-concept is disclosed here.

# Wordfence profile

This profile layers WordPress and Wordfence research preferences over the upstream Codex Security
Standard or Deep Scan. It intentionally does not replace the upstream coordinator: baseline
discovery remains independent and open-ended, the threat model remains investigation context, and
coverage and source validation retain their upstream meaning.

The static profile contains no credentials, private findings, or researcher data. The whitebox
adapter copies it into a private attempt and renders a per-run config that also names the current
official rules/scope snapshots and generated target context:

```bash
bin/wordfence-codex-security rerun TASK_ID --mode standard \
  --rules /private/policy/rules.txt --scope /private/policy/scope.txt
```

For a manual invocation, copy `codex-security.yaml`, `scan-instructions.md`, and
`program-policy.md` into a private run directory and add the target context and official snapshots
to that copied config's `scan.knowledge_base` list. A CLI `--knowledge-base` replaces the configured
list rather than appending to it, so do not accidentally drop `program-policy.md`.

Use `--mode deep` for repeated fresh complete scans with reducer-based saturation. Standard mode is
the default and already includes independent baseline discovery, source-backed threat modeling,
focused investigators, file-coverage reconciliation, and independent candidate validation.

The scanner discovers candidates and validates their source paths. It does not run a second generic
Docker workflow. The whitebox integration exclusively owns disposable WordPress reproduction,
negative controls, current-policy malicious triage, and `submit_ready` packaging.

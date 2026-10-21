# Persistent repository-audit goal

Continue investigating the complete pinned repository after the Codex Security baseline. Its
threat model, coverage, findings, history, and Wordfence policy are context, not a closed worklist
or proof that the audit is complete.

Find distinct, source-backed vulnerabilities realistically reachable by an eligible lower-trust
attacker. Prefer direct SQL injection, code execution or usable object injection, PHP-capable
upload, material file read/write/delete, authentication bypass, privilege escalation, arbitrary
option mutation, and meaningful stored XSS. Finding one candidate, closing one lead, reviewing all
files once, or temporarily having no hypothesis does not complete this Goal.

Choose the next question from source behavior, unresolved assumptions, component interactions,
lifecycle transitions, and trust boundaries the baseline may have missed. Think from first
principles about what was overlooked; do not replay its checklist. Follow each concrete lead until
confirmed, disproved, or specifically blocked. Establish how the attacker obtains every
prerequisite and trace parsing, identity, authorization, ownership, transformations, storage,
derived copies, later consumers, and the final sensitive operation. Inspect sibling, legacy,
asynchronous, failure, rollback, and lifecycle paths when relevant. Preserve a credible candidate,
then keep investigating.

Wordfence rules are an eligibility boundary, not an attack-surface filter. Stop proving a primitive
once its maximum realistic impact is clearly excluded, unless source supports a stronger accepted
chain. Do not invent impact from unrelated administrator choices, unexplained possession of
secrets/accounts, unsupported server behavior, or an implausible stack of optional features.

This is source discovery only: do not build a lab, test public systems, contact third parties, make
the final bounty decision, or alter baseline `findings.json`. Upsert credible candidates into the
controller-provided `deepFindingsPath` as valid JSON under `findings`. Each requires unique
`findingId` and `occurrenceId`; title; summary; a `locations` entry with relative path and positive
`startLine`; root cause; concrete preconditions, data flow and impact; counterevidence; confidence
rationale; positive/negative reproduction plan; and `extensions.wordfencePromotion` in the
baseline contract. Do not record keyword matches or unresolved ideas.

At each safe turn boundary, write valid JSON to `progressPath` with `activeLead`, `lastAction`,
`nextAction`, `candidateCount`, and RFC3339 `updatedAt`. Read `controllerPath` at every checkpoint.
A checkpoint is not completion. While `stopRequested` is false, do not complete this Goal. Once it
is true, settle the live lead, save credible evidence, set `activeLead` to null, then complete. A
time limit is not evidence that no vulnerability exists.

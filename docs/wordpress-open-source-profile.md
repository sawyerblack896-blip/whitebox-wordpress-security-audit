# Open-source WordPress audit profile

This repository publishes the reusable runtime of a private WordPress
security-audit workflow. It is intended for maintainers, defenders, and
researchers who want to run the generic acquisition, Goal, lab, and dashboard
components without receiving private policy or research assets.

## What is public

- provider, source, lab, and checkpointed Goal runtime;
- the deployment-owned prompt/schema adapter interface;
- a read-only dashboard and quota helpers;
- source-backed evidence principles and negative-control requirements;
- sanitized public CVE case studies in
  [`wordpress-security-case-studies.md`](wordpress-security-case-studies.md); and
- tests for persistence, external-validation identity binding, and promotion
  metadata.

## What is intentionally not public

- credentials, API keys, private account data, or real target hosts;
- unsubmitted or unpublished findings and proof-of-concept payloads;
- private Wordfence reports, tickets, internal moderation notes, scope rules,
  or qualification gates;
- current target rankings, scan queues, scoring weights, or competitive
  research plans; and
- per-run evidence, Docker state, or generated artifacts containing customer or
  researcher data.

The public runtime accepts current scope snapshots, target context, prompts, and
runtime evidence only from a deployment-owned private adapter. This separation
keeps the public project useful while protecting the live research system.

## Why this is useful to maintainers

The private workflow emphasizes a complete research Goal rather than a fixed
list of keywords or directories:

1. pin the release and establish the important trust boundaries;
2. perform open baseline discovery and record the threat model as context;
3. follow concrete source-backed chains until they are confirmed or disproved;
4. reproduce credible candidates in an isolated environment with a negative
   control; and
5. make one final coverage and scope decision using current policy.

This makes the system suitable for code review and regression testing without
turning a public repository into a catalog of live targets or unpublished
exploits.

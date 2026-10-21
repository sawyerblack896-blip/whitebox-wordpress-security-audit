# Open-source WordPress audit profile

This repository publishes a reusable security-audit workflow for WordPress
plugins. It is intended for maintainers, defenders, and researchers who need a
repeatable way to investigate a pinned plugin release without publishing private
research material.

## What is public

- the generic orchestration and resumable scan workflow;
- the WordPress/Wordfence policy adapter and its attacker-boundary checks;
- source-backed candidate and evidence schemas;
- disposable-runtime validation interfaces and negative-control requirements;
- sanitized public CVE case studies in
  [`wordpress-security-case-studies.md`](wordpress-security-case-studies.md); and
- tests for persistence, external-validation identity binding, and promotion
  metadata.

## What is intentionally not public

- credentials, API keys, private account data, or real target hosts;
- unsubmitted or unpublished findings and proof-of-concept payloads;
- private Wordfence reports, tickets, internal moderation notes, or scope
  conversations;
- current target rankings, scan queues, or competitive research plans; and
- per-run evidence, Docker state, or generated artifacts containing customer or
  researcher data.

The static profile is safe to copy into a public repository. A private adapter
adds current official scope snapshots, target context, and runtime evidence at
execution time. This separation keeps the public project useful while avoiding
the accidental disclosure of live research.

## Why this is useful to maintainers

The workflow emphasizes a complete research Goal rather than a fixed list of
keywords or directories:

1. pin the release and establish the important trust boundaries;
2. perform open baseline discovery and record the threat model as context;
3. follow concrete source-backed chains until they are confirmed or disproved;
4. reproduce credible candidates in an isolated environment with a negative
   control; and
5. make one final coverage and scope decision using current policy.

This makes the system suitable for code review and regression testing without
turning a public repository into a catalog of live targets or unpublished
exploits.

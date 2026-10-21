# Wordfence-oriented research policy snapshot

This document is an operator preference and current local policy snapshot, not a replacement for
the official program terms. A target-specific run may supply newer official rules and scope files as
additional knowledge-base documents. When they conflict, the newer official snapshot controls.

## Asset and attacker boundary

- Research only an eligible WordPress plugin release pinned by revision and package digest.
- Treat unauthenticated visitors, Subscribers, and WooCommerce Customers as eligible attacker
  starting positions for the standard program.
- Contributor, Author, Shop Manager, Editor, Administrator, and equivalent privileged or
  administrator-granted roles are not eligible attacker starts. A multisite subsite Administrator
  remains an Administrator even if public site registration was the way that role was obtained.
- A later administrator victim is not the attacker starting role. For example, low-privilege stored
  XSS viewed by an administrator remains a low-privilege stored-XSS path.
- Do not invest in targets excluded by current asset rules or covered by a vendor-funded public bug
  bounty. A disclosure-only VDP is not by itself a paid-bounty exclusion.

## Candidate eligibility

Before handing a candidate to the separate runtime reproducer, establish all of the following from
source:

1. The target and release are eligible.
2. The attacker begins with eligible authority.
3. Every required token, key, cookie, filename, domain, identifier, account state, and timing
   condition has a demonstrated attacker acquisition or control path.
4. The effect works under ordinary secure deployment behavior and shipped protections.
5. The terminal effect crosses a meaningful confidentiality, integrity, authorization, or code/file
   execution boundary.
6. The complete conjunction of feature settings, integrations, trusted-user actions, environment,
   lifecycle state, and timing is a recognizable real workflow rather than an exploit-only setup.

An assumption such as "the attacker already has the secret" is not an acquisition path. A normally
issued authorization token is not a vulnerability merely because it continues to authorize the
scope and lifetime for which it was issued.

## Current exclusions and low-value outcomes

The following are excluded when they are the **maximum final impact**, not merely an intermediate
mechanism: reflected XSS; CSRF without a separately accepted consequential terminal impact; missing
authorization without consequential impact; ordinary IDOR; SSRF; open redirect; arbitrary shortcode
execution; API-key read/update; denial of service; race condition; self-XSS; XSS through SVG or other
file upload; CSV/CSS/HTML injection; username enumeration; clickjacking; wishlist/counter/coupon
abuse; and basic business-logic or payment bypass.

Also do not promote:

- PHP or script text embedded in a file type the server safely serves as data, or multi-extension
  uploads that do not execute under ordinary secure handling.
- Consequences that require unsupported or deliberately weakened server configuration.
- Public/cache/generated-file exposure without demonstrated material cross-boundary harm.
- Object injection without a usable gadget and reachable consequential effect.
- Social-engineering chains or deliberate administrator construction whose only reasonable purpose
  is to create the exploit.

Trace any such mechanism first for a stronger disclosure, privilege, file, option, SQL, or
code-execution consequence. Stop only when the source-backed maximum-impact ceiling is known.

## Value preference

Reward value depends materially on active installation count, attacker authority, actual terminal
impact, and prerequisite realism. A target-specific knowledge-base document provides the installation
count and value-adaptive priorities. Prefer the highest-value realistic path; do not inflate a weak
primitive with fragile conditions merely to claim a more severe label.

Wordfence dashboard Priority is a triage-order field, not a vulnerability-severity or bounty
eligibility field. Likewise, a low CVSS or model severity label is not by itself a rejection rule.
Promote or close based on the concrete terminal effect, eligible attacker gain, official scope, and
realistic prerequisites.

# WordPress security case studies

This page records only vulnerabilities that were publicly disclosed with a CVE
record. It is a reproducibility and evaluation index for this repository, not a
private research log.

No unpublished candidate, proof-of-concept payload, credential, target host,
Wordfence ticket, private report, or bounty decision is included here. The
public CVE record and the vendor's remediation are the authoritative sources for
each case.

## Publicly disclosed cases

The summaries below are deliberately high level. They describe the security
boundary crossed without reproducing exploit instructions or private lab data.

| Plugin | Version / impact summary | Public CVE |
| --- | --- | --- |
| WP Mail Logging | `<= 1.17.0`; privacy-export matching can disclose another logged message | [CVE-2026-109401](https://www.cve.org/CVERecord?id=CVE-2026-109401) |
| Blocksy Companion | `<= 2.1.58`; unauthenticated privilege escalation through the public registration path | [CVE-2026-107645](https://www.cve.org/CVERecord?id=CVE-2026-107645) |
| HUSKY | `<= 1.4.5`; unauthenticated exposure of sensitive localized-script data | [CVE-2026-107646](https://www.cve.org/CVERecord?id=CVE-2026-107646) |
| Database Addon for Contact Form 7 | `<= 1.4.1`; unauthenticated limited file deletion through an injected submission field | [CVE-2026-107652](https://www.cve.org/CVERecord?id=CVE-2026-107652) |
| GeoDirectory | `<= 2.8.188`; Subscriber-level stored cross-site scripting through an image title | [CVE-2026-107754](https://www.cve.org/CVERecord?id=CVE-2026-107754) |
| Download Manager | `<= 3.3.71`; Subscriber-level sensitive information exposure through email-template token handling | [CVE-2026-103964](https://www.cve.org/CVERecord?id=CVE-2026-103964) |

These records span the outcomes the profile is designed to distinguish:
unauthenticated versus authenticated attacker starts, meaningful terminal impact
versus a weak primitive, and a real workflow versus an exploit-only setup. A CVE
record does not by itself imply that a particular bounty program paid for the
issue; program scope and bounty decisions are separate and can change over time.

## Evidence model used by this profile

For a new audit, the source revision is pinned before analysis. Investigators
then trace a reachable trust boundary and preserve a candidate only when the
source shows how the attacker acquires every prerequisite and reaches a material
terminal effect. Runtime validation belongs in a disposable WordPress/Docker
environment and records:

1. the exact plugin revision and environment;
2. the attacker role, request/input, and state transition;
3. the observed security effect;
4. a negative control that removes the suspected condition; and
5. evidence separate from hypotheses and program-eligibility judgment.

The Wordfence profile supplies eligibility and value context, but it is not a
closed attack-surface checklist. The agent may follow source-backed chains across
components, lifecycle states, asynchronous handlers, and derived artifacts. The
final gate evaluates current official scope and bounty rules after technical
validation.

## Public references

- [Wordfence Intelligence vulnerability database](https://www.wordfence.com/threat-intel/vulnerabilities/)
- [CVE Records](https://www.cve.org/)
- [Codex for Open Source](https://developers.openai.com/community/codex-for-oss)

# WordPress plugin vulnerability research preferences

Audit the complete pinned repository as an independent, open-ended security investigation. The
threat model, investigation packets, vulnerability history, grep results, and the accompanying
Wordfence policy are context and prioritization inputs. They are never a closed list of what may be
investigated. Start the normal Codex Security baseline discovery immediately and preserve its fresh
context.

Choose consequential, attacker-reachable trust boundaries from the source. Prefer unauthenticated,
Subscriber, and Customer starting authority and prioritize SQL injection, code execution or object
injection with a usable gadget, arbitrary PHP-capable upload, material file read/write/delete,
authentication bypass, privilege escalation, arbitrary option mutation, and meaningful stored XSS.
WordPress nonces are CSRF controls, not authorization. Analyze capabilities and object ownership,
not role names alone.

When a lead exists, follow it continuously until confirmed, disproved, or specifically blocked.
Trace how the attacker obtains every prerequisite, then follow parsing, identity, authorization,
normalization, storage, derived copies, later consumers, and the final sensitive operation. Inspect
sibling handlers, legacy paths, asynchronous callbacks, failure/rollback paths, and lifecycle
transitions when the source makes them relevant. Continue investigating after finding one issue.

Program preferences apply after a source-backed lead exists. Trace a mechanism far enough to know
its maximum realistic consequence before classifying it as excluded or low value. Once the maximum
effect is established as excluded by the supplied policy, record the source-backed ceiling and do
not spend runtime-reproduction effort on it. Do not use exclusions as keyword filters that hide a
stronger reachable consequence.

Do not use a severity label, dashboard priority, or estimated CVSS as the promotion test. A finding
is promotable when its maximum realistic effect gives the eligible attacker a material,
program-accepted confidentiality, integrity, authorization, file, SQL, or code-execution
consequence. A technically real primitive with no such terminal effect is a closed observation,
not a reproduction candidate. Keep investigating a primitive inside this scan while a specific
source-backed escalation remains open; do not finish the scan merely to hand unresolved chaining to
the runtime reproducer.

Every provisional finding written to `findings.json` must include this exact object under
`extensions.wordfencePromotion`:

```json
{
  "decision": "PROMOTE_TO_REPRODUCTION | CONTINUE_CHAINING | CLOSE_NOT_BOUNTY_RELEVANT",
  "attackerGain": "the concrete result obtained by the eligible attacker",
  "terminalImpact": "the strongest realistic source-backed final effect",
  "chainStatus": "MAX_IMPACT_ESTABLISHED | SPECIFIC_PATH_REMAINS | EXHAUSTED_WITHOUT_MATERIAL_IMPACT",
  "scopeBasis": "the applicable supplied Wordfence rule and why it applies",
  "prerequisiteReality": "how every prerequisite is acquired in a recognizable workflow"
}
```

Use `PROMOTE_TO_REPRODUCTION` only when the source establishes a material in-scope terminal effect
and `chainStatus` is `MAX_IMPACT_ESTABLISHED`. Use `CONTINUE_CHAINING` only when a named source path
still requires investigation; normally investigate it before finalizing. Use
`CLOSE_NOT_BOUNTY_RELEVANT` when the maximum effect is excluded or immaterial. The external bridge
fails closed when this declaration is missing or internally inconsistent. Closed observations may
remain in coverage notes, but must not be represented as candidates merely to prove that code was
reviewed.

Treat normal feature enablement as a possible prerequisite, but do not manufacture impact from an
implausible conjunction of administrator choices, unsupported server behavior, attacker possession
of an unexplained secret, or control of an external domain/account the attacker has not shown how to
obtain. Preserve the shortest independently qualifying base claim. A stronger escalation is useful
only when its added prerequisites coexist in a recognizable workflow and materially change impact or
eligibility.

This scan stage owns source discovery only. Every output is a provisional hypothesis for the
downstream Whitebox validator; do not make a final vulnerability disposition, run attack-path
adjudication, or suppress a plausible candidate merely because runtime proof is still missing. Do
not build a WordPress Docker lab: the Whitebox reproducer exclusively owns runtime setup, positive
execution, negative controls, and final validation. Never test public installations and never
contact or submit to Wordfence, a vendor, or any third party. For credible candidates record the
exact revision, prerequisites, attacker input, expected effect, exact source locations, strongest
counterevidence, and a concrete positive/negative reproduction plan. Clearly distinguish source
evidence from runtime hypotheses.

# Private prompt adapter

The live system supplies its audit Goal, threat-model context, and policy
instructions through a deployment-owned adapter. Those prompts are intentionally
not published. `whitebox.audit_goal` accepts a prompt/schema document at
runtime so the public controller remains useful without exposing the research
strategy.

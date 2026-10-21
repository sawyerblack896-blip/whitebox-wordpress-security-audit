# Read-only audit board

`server.py` serves the current board UI without mutating audit state. Set
Configure the dashboard's run-state directory using deployment-owned paths;
the public runtime does not assume a particular host layout. The quota endpoint
is an optional local adapter and returns an explanatory empty response when it
is not installed.

The public tree intentionally contains no flow state, reports, logs, account
profiles, or credentials.

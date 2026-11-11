## Prose

When you write or change Markdown that a person reads, use the nossaifd skill, and follow all of its
steps. Its step 6 gives the page to a subagent that did not write it, for the pass of the declaude skill
by Oskar Austegard. After step 8, record each page:

```bash
uv run --no-project --quiet python .agents/skills/nossaifd/scripts/prose_gate.py record page.md
```

A hook checks, when you end your turn, that each page that the turn changed passed the checker and has a
record. If a page is not prose for a person, do not record it, and tell the user so. Keep each bad
example that a page shows on purpose.

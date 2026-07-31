# Hermes runtime Python

Always use:

```bash
~/.hermes/bin/hermes-python
# or
~/.hermes/hermes-agent/venv/bin/python
```

Do **not** use Homebrew `/opt/homebrew/bin/python3` (currently 3.14, externally-managed).
Hermes CLI itself already points at the venv via `~/.local/bin/hermes`.

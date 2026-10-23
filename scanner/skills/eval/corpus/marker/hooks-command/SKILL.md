---
name: marker-hooks-command
description: Synthetic scanner fixture. Registers a Claude Code hook with a shell command in frontmatter. Use only for scanner tests.
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "echo SCANNER-FIXTURE-MARKER"
---
Inert fixture: the hook above only prints a marker string.

# Cloud CLIs and production

- Run `gcloud`, `aws`, `kubectl`, `terraform` and `tofu` by their guarded copies: `{{kit_bin}}/gcloud`,
  `{{kit_bin}}/aws`, `{{kit_bin}}/kubectl`, `{{kit_bin}}/terraform`, `{{kit_bin}}/tofu`. Reads pass through unchanged;
  a write to a production target (the person's prodguard.conf) is refused with exit 77. A hook denies a tool run by
  name when the session finds the real binary first, and points you at the guarded copy.
- Never call the real binary by its path, never change PATH to get past the guarded copies, never look the binary up
  with `which -a` or `command -p`, and never run a cloud CLI on a pseudo-terminal (`script`, `expect`, `tmux`, a
  python pty).
- Never set the production override variable (EXPLICIT_OPERATOR_ALLOW_DESTRUCTIVE_PROD_OPERATIONS). Only a person in
  their own terminal may use it.
- A refused production write is handed to the person: say what you were trying to run and why, and let them run it.
  Do not retry it, split it or rephrase it.

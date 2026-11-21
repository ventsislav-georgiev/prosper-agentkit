<!-- DRAFT for operator approval: written fresh for the kit; not yet approved. -->
# Named workers

This kit installs eight worker agents: `worker-haiku`, `worker-sonnet-low`, `worker-sonnet-medium` and
`worker-opus-low`, `-medium`, `-high`, `-xhigh` and `-max`. Each is the general-purpose agent with its model, effort
and tools pinned in its frontmatter (`worker-haiku` is read-only).

- When you hand work to a subagent, spawn one of these by name. Do not use the general-purpose agent: the Agent call
  has no effort parameter, so only a named worker runs at a known effort.
- Pick the tier by the work:
  - `worker-haiku`: locating and reading only (find a file, read a log, quote a line); it never edits.
  - `worker-sonnet-low` / `worker-sonnet-medium`: fully specified work that a test, build or script checks.
  - `worker-opus-medium`: the default for everything harder (multi-file changes, debugging with an unknown cause).
  - `worker-opus-low`: single-file, fully specified work that is too hard for Sonnet.
  - `worker-opus-high`: the redo after a `medium` worker's review failed, never a first pick.
  - `worker-opus-xhigh` / `worker-opus-max`: only an extreme, critical entry; slow and token-heavy.
- Give the worker everything it needs in the prompt: it does not see this conversation. Name the kit's bin folder
  as `KIT_BIN={{kit_bin}}`: the agent files call the kit's tools through `$KIT_BIN`.
- Ask it for a short report and a file with the full result, and check that file before you rely on it.

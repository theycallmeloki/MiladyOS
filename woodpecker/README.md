# MiladyOS × Woodpecker — Phase A pilot (cli-exec)

See `WOODPECKER_MIGRATION.md` for the full plan + rulings (2026-09-01: forge =
none, cli-exec only; MCP = keep native + `ni-c` later; base = debian:13.4).

## What's here

| File | Purpose |
|------|---------|
| `install-cli.sh` | pinned woodpecker-cli **v3.18.0** installer (sha256-verified); Dockerfile rebase + builder.sh dependency |
| `runner.yml` | ad-hoc command runner — the `execute_command` MCP re-point (local backend) |
| `scratch-build.yml` | build a Dockerfile on the **host daemon** + push with registry-skip guard — the scratch-builds-on-the-box replacement |

## Proven (2026-09-01, woodpecker-cli 3.18.0)

1. `woodpecker-cli exec --local --repo miladyos/MiladyOS woodpecker/runner.yml`
   → step container runs on the host daemon, CI metadata injected
   (`CI_PIPELINE_NUMBER`, `CI_EVENT`). `$CI_REPO` was empty via `--repo` —
   env name differs in exec mode; not needed for the runner pattern.
2. Docker backend + `--volumes /var/run/docker.sock:/var/run/docker.sock`
   + `--repo-trusted-volumes` + `docker:cli` step image → `docker build` on
   the host daemon, image runs, cleanup OK. (bash:5 step image has no docker
   CLI — use `docker:cli`.)

Gotchas: step `volumes:` requires `--repo-trusted-volumes`; YAML plain scalars
choke on `: ` — use block scalars (`|`) for shell.

## Next (Phase A)

- Dockerfile: `FROM debian:13.4`, run `woodpecker/install-cli.sh` (drop
  plugin-manager/plugins.txt/JCasC/theme + the legacy user).
- `miladyos_mcp.py`: `execute_command` → `woodpecker-cli exec ... runner.yml`;
  `create_pipeline` → write pipeline + exec.
- Keep `miladyos:pre-woodpecker` tag for rollback; GH Actions unchanged.

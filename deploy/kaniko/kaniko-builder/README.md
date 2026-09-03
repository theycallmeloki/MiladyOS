# kaniko-builder — the sandman build bus

> STATUS (2026-09-04): the standalone `kaniko-builder` sandman pipeline is
> RETIRED. This folder is preserved as its definition (spec + image Dockerfile
> + runner). Replacement: the woodpecker buildbus `kaniko-build` stage
> (`sandman-pipelines/buildbus/`, live gitea `milady/buildbus`) submits the
> same KanikoBuild CRs via the same `kaniko-submit.py` — one in-cluster build
> front-door. Re-instantiate the data-plane bus from this spec if the generic
> "seed a Dockerfile, get an in-cluster image" interface is ever needed again.
> Moved here from `sandman-pipelines/templates/kaniko-builder/` (it is
> MiladyOS kaniko machinery, not a port template).

Pipeline: datum dirs on the `builds` input repo become KanikoBuilds in the
miladyos cluster, pushed to `miladyosregistry.transparentlyrotatableproxy.site`.

Anything with sandman access can trigger a container build and follow it
end to end (job state, logs, output commits, registry tag):

```sh
# seed a build request (one datum = one KanikoBuild)
sandman repo create builds            # once
sandman put ./seed-example builds@master:my-image
sandman job list kaniko-builder       # follow
```

## Datum contract

Each top-level entry under `builds@master` is one build request
(`glob: "/*"`). A datum directory contains:

- `spec.json` — `{"destination": "miladyosregistry.../<image>:<tag>"}` (also
  honors `timeoutSeconds` via the transform env `KANIKO_TIMEOUT`)
- `Dockerfile` at the datum root
- build context files (a `.dockerignore` is respected)

The transform runs `kaniko-submit.py --context <datum dir>`; the helper's
registry-skip guard makes re-seeding idempotent (same tag exists → no-op).

## Runtime

- Secret `kubeconfig` (key `KUBECONFIG_CONTENT`) holds a cluster kubeconfig
  — bound via `transform.secrets` → env.
- Transform image `miladyosregistry.../kaniko-builder:<tag>` (Dockerfile in
  this dir; based on the kaniko-submit tool image).

## Gotchas (v0.2.43, sandman + kaniko fabric)

- CLI `pipeline create --secret NAME` produces an invalid mount (EnvVar=NAME
  without Key → 400) — create pipelines from the JSON spec (`-f`) instead.
- A transform with no `cmd` never executes (engine treats it as a
  passthrough: input mirrored to output, instant success).
- The datum staging dir is the env var named after the input repo
  (`$builds`), NOT `$in`; subtree datums nest one level
  (`$builds/<datum>/spec.json`).
- KanikoBuild contexts >~128KB base64 need `spec.contextConfigMap` (see
  MiladyOS deploy/kaniko) — kaniko-submit.py picks automatically.

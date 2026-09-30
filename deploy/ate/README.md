# Agent Substrate + Agent Executor (ax) on MiladyOS

Brings up [Agent Substrate](https://github.com/agent-substrate/substrate) and
[ax](https://github.com/google/ax) on this cluster. Substrate is the sandboxed
actor runtime; ax is the declarative orchestrator that sits on top of it.

Neither project publishes prebuilt images, so the install builds everything from
a source checkout with `ko` and pushes to the in-cluster registry. A working Go
toolchain is a prerequisite: Substrate requires **go 1.27**, while this machine's
mise shims defaulted to 1.15/1.16.

## Order

```bash
# 0. cluster prerequisites (see the Talos Prerequisites section of ../README.md):
#    - certificates.k8s.io v1beta1 PodCertificateRequest + ClusterTrustBundle
#      feature gates and apiserver runtime-config on every node
#    - the namespaces below

# 1. namespaces + PodSecurity
kubectl apply -f deploy/ate/namespaces.yaml      # ate-system (privileged), ax-system

# 2. object store + telemetry sink
kubectl apply -f deploy/ate/rustfs.yaml          # S3 store, creates bucket ate-snapshots
kubectl apply -f deploy/ate/otel-collector.yaml  # OTLP sink; GKE's managed endpoint does not exist here

# 3. patch the substrate checkout for a bare, non-GCP cluster
cd <substrate checkout>
git apply /path/to/deploy/ate/substrate-bare-cluster.patch
go build -mod=vendor -o bin/ate-setup ./cmd/ate-setup

# 4. install the control plane
export KO_DOCKER_REPO=miladyosregistry.transparentlyrotatableproxy.site/ate-images
export BUCKET_NAME=ate-snapshots
unset PROJECT_ID CLUSTER_NAME CLUSTER_LOCATION   # keep these unset: they trigger gcloud
bin/ate-setup deploy ate-system \
  --otlp-endpoint http://opentelemetry-collector.ate-system.svc.cluster.local:4317 \
  --rollout-timeout 300s

# 5. worker images + pool (the installer does neither)
bin/ate-setup publish worker-images              # prints ateom-gvisor/ateom-microvm digests
# put the printed ateom-gvisor digest into deploy/ate/workerpool.yaml, then:
kubectl apply -f deploy/ate/workerpool.yaml

# 6. ax
KO_DOCKER_REPO=miladyosregistry.transparentlyrotatableproxy.site/ax-images \
  ko build ./cmd/ax-server --platform=linux/amd64 --tags latest   # in the ax checkout
# put the printed digest into deploy/ax/ax-system.yaml, then:
kubectl apply -f deploy/ax/ax-system.yaml
```

## Why substrate is patched

`substrate-bare-cluster.patch` is a `git diff` of `manifests/ate-install/` with
four changes, each load-bearing:

| File | Change | Why |
|---|---|---|
| `base/kustomization.yaml` | drop `atenet-router-monitoring.yaml` | It is a `monitoring.googleapis.com/v1` PodMonitoring (Google Managed Prometheus CRD) that does not exist here, and it is in the base bundle, so a stock install fails to apply |
| `atelet.yaml` | `--gcp-auth-for-image-pulls=false` | The default pulls through GCP ADC, which this cluster has no access to |
| `atelet.yaml`, `ate-api-server.yaml` | `ATE_STORAGE_BACKEND: s3` + `AWS_*` pointing at rustfs | The default is GCS via ADC. Snapshots are addressed as `gs://<bucket>/<prefix>` regardless of backend and resolved through the configured store |
| `postgres/postgres.yaml` | storage 500Gi → 20Gi, cpu request 2 → 250m, limit 16 → 2 | The bundled claim is sized for a GKE node; 500Gi cannot bind against a ~240Gi Longhorn node, and a 2-CPU request is half a Talos worker |

The `gs://gvisor/...` asset URLs in `SandboxConfig/gvisor-default` are left
alone deliberately: atelet tries an anonymous GCS client first for public
buckets and only falls back to the cluster store, so runsc stages from the
public gVisor releases bucket unchanged.

## Deviations from upstream worth remembering

- **`ate-system` must be privileged.** atelet mounts four hostPaths and runs as
  root; worker pods add a dozen capabilities and hostPath-mount `/var/lib/ate`.
  Baseline PodSecurity rejects both. `ax-system` needs no such thing — it runs
  only ax-server and redis.
- **Worker pools are yours to create**, not the installer's. Set
  `spec.workerImage` to the digest `publish worker-images` prints, and re-run it
  whenever the substrate revision changes: the worker image is version-pinned to
  the control plane.
- **Actors have no egress until you grant it.** As of v0.2.0 the egress gateway
  enforces `EgressPolicy`: an actor without a policy cannot reach anything,
  including a model API. Expect to add one before any agent can call out.
- **`ate.dev/substrate-version` is stamped on nodes at install time only.** A
  node added later hosts no workers until it carries the label.
- **Do not auto-upgrade or use preemptible worker nodes.** An actor still awake
  when a worker is deleted passes the 30-minute suspend window and becomes
  `ACTOR_STATE_CRASHED`, which is terminal.
- **gVisor needs user namespaces, which Talos disables.** Talos defaults
  `user.max_user_namespaces` to 0. The kernel's `create_user_ns()` returns
  `ENOSPC` when that limit cannot be satisfied, so the failure surfaces as
  `cannot create gofer process: gofer: fork/exec /proc/self/exe: no space left
  on device` — which reads like a full disk but is not. Apply
  `deploy/ate/gvisor-userns-sysctl.yaml` to every node that hosts workers.
- **The installer rewrites `ate-api-authentication` on every run.** Its
  generated config omits `certificateAuthorityFile`/`discoveryTokenFile` unless
  the issuer is the in-cluster default, on the assumption that any other issuer
  is anonymously discoverable. Talos runs `--anonymous-auth=false`, so the JWKS
  fetch 401s and every client JWT is rejected as `invalid bearer token`.
  Re-apply `deploy/ate/authentication-config.yaml` after any
  `deploy ate-system`.

## Verify

```bash
# control plane + worker pool
kubectl -n ate-system get deploy,sts,ds
kubectl -n ate-system get workerpools

# an actor actually running under gVisor
ax apply -f deploy/ax/simple-task.yaml
ax get tasks                      # expect PHASE=Running and a WORKER-IP
ax describe task simple-task      # expect Ready=True, WorkspaceReady=True
ax ssh simple-task -- uname -a    # expect: Linux ... 4.19.0-gvisor ...
ax ssh simple-task -- ls -la /workspace
```

`uname -r` reporting `4.19.0-gvisor` is the proof that the workload is inside a
gVisor sandbox rather than the host kernel, and `dmesg` inside the sandbox shows
gVisor's boot banner.

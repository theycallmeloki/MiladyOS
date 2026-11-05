# Agent Substrate + Agent Executor (ax) on MiladyOS

Brings up [Agent Substrate](https://github.com/agent-substrate/substrate) and
[ax](https://github.com/google/ax) on this cluster. Substrate is the sandboxed
actor runtime; ax is the declarative orchestrator that sits on top of it.

Pinned versions:

| Thing | Revision | Images |
|---|---|---|
| Substrate | `0b635b80` (module `go.ate.dev/substrate`) | upstream release **v1.0.0-rc.3**, `ghcr.io/agent-substrate/substrate/<component>:v1.0.0-rc.3` |
| ax | `2187dd4` | built here with in-cluster kaniko, `ax-images/ax-server`, `ax-images/ax-task-runner` |

Upstream releases images now, so Substrate is **not** built from source. The
release publishes `ate-idp-server`, `ateapi`, `atecontroller`, `atelet`,
`atenet`, `ateworker-gvisor`, `ateworker-microvm`, `kubernetes-secrets`,
`objectstore-plugin`, `podcertcontroller`, and `envoy-dataplane`. The packages
are public: the cluster pulls them anonymously (verified from a worker). Only
`ate-setup` itself is built locally, because the manifests still need this
repo's bare-cluster patch.

## Order

```bash
# 0. cluster prerequisites (see the Talos Prerequisites section of ../README.md):
#    - certificates.k8s.io v1beta1 PodCertificateRequest + ClusterTrustBundle
#      feature gates and apiserver runtime-config on every node
#    - the namespaces below
kubectl apply -f deploy/ate/namespaces.yaml      # ate-system (privileged), ax-system

# 1. object store + telemetry sink
kubectl apply -f deploy/ate/rustfs.yaml          # S3 store, creates bucket ate-snapshots
kubectl apply -f deploy/ate/otel-collector.yaml  # OTLP sink; GKE's managed endpoint does not exist here

# 2. CRD storage-version migration (only when coming from the v0.2.0 install).
#    v1.0.0-rc.3 serves ate.dev/v1; the old installs stored ate.dev/v1alpha1, and
#    the apiserver rejects the new CRDs while status.storedVersions names a
#    version the new spec dropped. The only custom resources that exist are
#    reproducible from this repo, so delete them, clear storedVersions, and let
#    the installer recreate them:
kubectl -n ate-system delete workerpool gvisor-workers
kubectl -n ate-system delete sandboxconfig gvisor-default
for crd in csidriverconfigs sandboxconfigs workerpools; do
  kubectl patch crd $crd.ate.dev --subresource=status --type=merge \
    -p '{"status":{"storedVersions":["v1"]}}'
done

# 3. patch a substrate checkout and build the installer
git clone https://github.com/agent-substrate/substrate ~/build/substrate
cd ~/build/substrate && git checkout 0b635b80
git apply ~/repos/MiladyOS/deploy/ate/substrate-bare-cluster.patch
export PATH=$HOME/.local/go/bin:$PATH        # go 1.27.3
go build -o bin/ate-setup ./cmd/ate-setup
go build -o bin/kubectl-ate ./cmd/kubectl-ate    # for atespaces and access policies

# 4. install the control plane from the published images
#    --kubeconfig pins the apiserver: the Talos VIP (.45) flaps, so point at a
#    control-plane node directly. --context makes the installer skip its
#    gcloud get-credentials path.
./bin/ate-setup deploy ate-system \
  --kubeconfig ~/.kube/ate-rc3-config --context admin@miladyos --no-dev-env \
  --image-repo ghcr.io/agent-substrate/substrate --image-tag v1.0.0-rc.3 \
  --credential-provider '{"name":"k8s.io"}' \
  --snapshot-location gs://ate-snapshots/ --storage-bucket-name ate-snapshots \
  --snapshot-transfer-gsa-name unused --gcp-project-id unused \
  --sandbox-classes gvisor --rollout-timeout 420s \
  --ingress-allowed-spiffe-ids spiffe://cluster.local/ns/ax-system/sa/ax-server

# 5. re-apply the authentication fix if the installer rewrote it (it logs
#    "Rewriting ate-system/ate-api-authentication" when it does)
kubectl apply -f deploy/ate/authentication-config.yaml

# 5b. allow gVisor in the kernel. Talos disables user namespaces, and gVisor
#     cannot start its gofer without them. gvisor-userns-sysctl.yaml is the
#     persistent Talos machine-config patch; this cluster's Talos config is
#     hand-managed, so the runtime DaemonSet below applies the same sysctl on
#     every labelled worker node instead.
kubectl apply -f deploy/ate/gvisor-userns-runtime.yaml

# 5c. rc.3 enforces authorization. ax creates its own atespaces, so it needs
#     the global owner role; apply this as the bootstrap owner (ate-client).
~/build/substrate/bin/kubectl-ate create access-policy --global \
  -f deploy/ate/ax-access-policy.yaml

# 6. worker images + pool (the installer does neither)
#    node label: the WorkerPool selector keys on it; atelet itself runs on every
#    untainted node
kubectl label node talos-2eq-d5g talos-5oi-fsg talos-e03-w4r talos-of4-m85 \
  ate.dev/substrate-version=v1.0.0-rc.3 --overwrite
kubectl apply -f deploy/ate/workerpool.yaml

# 7. ax (see "Build the ax images" below for the image digests)
kubectl apply -f deploy/ax/ax-system.yaml
```

`--snapshot-transfer-gsa-name` / `--gcp-project-id` are dummy values: rc.3 still
requires them off kind (`RequireTransferServiceAccount`), but the object-store
plugin runs with `ATE_STORAGE_BACKEND=s3`, so the credential exchange and the
GSA are never used. Passing `--context` keeps `PROJECT_ID` from triggering
`gcloud container clusters get-credentials`.

For reference, the exact cutover from the old v0.2.0 install also deleted the
obsolete `atelet-v0-2-0-32-gafb62e18-dirty` DaemonSet and any old
ImagePullBackOff pods pinned to the previous registry digests.

## Build the ax images

The host has no docker/podman, so ax's images are built by an in-cluster kaniko
pod from `Dockerfile.<image>` copies of upstream's Dockerfiles with a golang
build stage (upstream's copies `bin/linux_<arch>/...`, which no checkout has).
Context is a `git clone` of google/ax at `2187dd4` into an emptyDir; the derived
Dockerfile is mounted from a ConfigMap and copied into the context. Kaniko
pushes to `kaniko-registry.sandman.svc.cluster.local:5000/ax-images/<name>`,
which is the same registry the nodes pull as
`miladyosregistry.transparentlyrotatableproxy.site`.

After a build, read the digest and pin it in the manifests:

```bash
curl -sI -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
  http://192.168.1.202:5000/v2/ax-images/ax-server/manifests/v1.0.0-rc.3 |
  tr -d '\r' | grep -i docker-content-digest
```

Current digests (all built from ax `2187dd4`):

| Image | Digest |
|---|---|
| `ax-images/ax-server` | `sha256:fed30d335a5fd45bd6bb423cb328b36da47a135e84c393880cfcfbc36207cb81` |
| `ax-images/ax-task-runner` | `sha256:934ad7d7b282a8d7823d287bcc481bfcbbd4930a380a7eb381663f71d8622f83` |

`deploy/ax/ax-system.yaml` pins ax-server; `AX_DEFAULT_TASK_IMAGE` there pins
the task-runner, and the task examples (`simple-task.yaml`,
`milady-improve.yaml`, `sandman-mcp.yaml`) pin it themselves because a Task
image must be digest-pinned.

ax at `2187dd4` keeps its state in PostgreSQL (`--store`, `ax-postgres`) and no
longer uses Redis — the Redis Streams queue was removed upstream. `ax-system`
also needs the `ate.dev/api-access=true` namespace label so
ate-api-server's NetworkPolicy admits it.

## Why substrate is patched

`substrate-bare-cluster.patch` is a `git diff` of `manifests/ate-install/` with
four changes, each load-bearing:

| File | Change | Why |
|---|---|---|
| `base/kustomization.yaml` | drop `atenet-router-monitoring.yaml` | It is a `monitoring.googleapis.com/v1` PodMonitoring (Google Managed Prometheus CRD) that does not exist here, and it is in the base bundle, so a stock install fails to apply |
| `atelet.yaml` | drop `--image-credential-provider-config`/`-bin-dir` and their `/home/kubernetes/bin`, `/etc/srv/kubernetes` hostPaths | These are GKE node paths (Talos has neither); without a provider, worker images pull anonymously |
| `atelet.yaml`, `ate-api-server.yaml` | `objectstore-plugin` initContainer: `ATE_STORAGE_BACKEND: s3` + `AWS_*` pointing at rustfs | rc.3 moved object storage off atelet/ate-api-server onto the sidecar (each exits if `ATE_STORAGE_BACKEND` is set on it). The default is GCS via ADC. Snapshots stay addressed as `gs://<bucket>/<prefix>`; the backend resolves them |
| `postgres/postgres.yaml` | storage 500Gi → 20Gi, cpu request 2 → 250m, limit 16 → 2 | The bundled claim is sized for a GKE node; 500Gi cannot bind against a ~240Gi Longhorn node, and a 2-CPU request is half a Talos worker |

The `gs://gvisor/...` asset URLs in `SandboxConfig/gvisor-default` are left
alone deliberately: the object-store plugin hands public buckets back to atelet,
which reads them anonymously from the public gVisor releases bucket.

## Deviations from upstream worth remembering

- **`ate-system` must be privileged.** atelet mounts four hostPaths and runs as
  root; worker pods add a dozen capabilities and hostPath-mount `/var/lib/ate`.
  Baseline PodSecurity rejects both. `ax-system` needs no such thing.
- **Worker pools are yours to create**, not the installer's. `workerImage` is
  version-pinned to the control plane, so bump it with the release tag. rc.3
  renamed it `ateworker-gvisor` (older releases: `ateom-gvisor`) and the CR is
  `ate.dev/v1` with `sandboxClasses` instead of `sandboxClass`.
- **The installer can block on old pods.** It waits for a Deployment rollout to
  finish, and a terminating pod from the previous ReplicaSet counts. Delete any
  old pod pinned to a dead digest before judging a failed rollout: the first
  cutover run timed out at 300s on exactly that.
- **Projected pod-certificate volumes take minutes to mount on a fresh pod.**
  kubelet retries with exponential backoff while the podcertificate-controller
  issues, and logs `credential bundle is not issued yet` until the mount
  succeeds. `--rollout-timeout 420s` covers it; the issuance itself takes
  seconds.
- **rc.3 enforces authorization.** `ate-api-server` checks every call against
  an embedded OpenFGA model and `ate-client` is the bootstrap owner. Without
  `ax-access-policy.yaml` ax fails with `lacks "can_create_atespace" on
  "global:root"`, because ax creates its atespaces and templates itself.
- **ax here is newer than the pinned Substrate.** rc.3's router Service serves
  443/8444 only, and its PodCertificateRequest API predates
  `spec.stubPKCS10Request`; ax `2187dd4` requests that field and port-forwards
  the router's port 80 for `ax ssh`. Tasks run (`PHASE=Running`, worker IP
  assigned, real `runsc` sandbox), but `ax ssh` and workspace readiness need a
  Substrate revision newer than v1.0.0-rc.3 or an ax pinned to it.
- **Actors have no egress until you grant it.** The egress gateway enforces
  `EgressPolicy`: an actor without a policy cannot reach anything, including a
  model API.
- **The installer rewrites `ate-api-authentication` when it changes shape.**
  rc.3 removed the `actorIdentityJWTProvider` key from the schema and
  regenerates the ConfigMap without `certificateAuthorityFile` /
  `discoveryTokenFile`, on the assumption that a non-default issuer is
  anonymously discoverable. Talos runs `--anonymous-auth=false`, so the JWKS
  fetch 401s and every client JWT is rejected as `invalid bearer token`.
  Re-apply `deploy/ate/authentication-config.yaml` after any
  `deploy ate-system` that logs `Rewriting ate-system/ate-api-authentication`.
- **Do not auto-upgrade or use preemptible worker nodes.** An actor still awake
  when a worker is deleted passes the 30-minute suspend window and becomes
  `ACTOR_STATE_CRASHED`, which is terminal.
- **gVisor needs user namespaces, which Talos disables.** Talos defaults
  `user.max_user_namespaces` to 0. The kernel's `create_user_ns()` returns
  `ENOSPC` when that limit cannot be satisfied, so the failure surfaces as
  `cannot create gofer process: gofer: fork/exec /proc/self/exe: no space left
  on device` — which reads like a full disk but is not. Apply
  `deploy/ate/gvisor-userns-sysctl.yaml` to every node that hosts workers.

## Verify

```bash
# control plane + worker pool
kubectl -n ate-system get deploy,sts,ds,workerpools
kubectl -n ate-system get pods          # no ImagePullBackOff; atelet 4/4
kubectl -n ax-system get pods           # ax-server + ax-postgres

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

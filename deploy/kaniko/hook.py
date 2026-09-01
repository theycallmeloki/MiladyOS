#!/usr/bin/env python3
"""KanikoBuild sync hook for metacontroller.

Runs IN-CLUSTER (was a workstation script on 192.168.1.147:8090 with a
hardcoded kubeconfig — single point of failure). Uses the pod's service
account; no kubeconfig, no kubectl binary. Implements the metacontroller
composite-controller webhook protocol: given a KanikoBuild object, returns
the desired children (the kaniko pod) and the CR status.

A build is executed as a kaniko-executor pod (no Docker daemon anywhere):
  - an initContainer unpacks the base64 tar.gz context into an emptyDir
  - kaniko builds from tar:// and pushes to the configured registry
  - on success/failure the pod is GC'd and status carries the outcome
    (failure includes the kaniko log tail)

Endpoints:
  POST /sync   metacontroller sync hook
  GET  /healthz
"""
import base64
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kubernetes import client as k8s, config

REGISTRY = os.getenv("KANIKO_REGISTRY", "miladyosregistry.transparentlyrotatableproxy.site")
NAMESPACE = os.getenv("KANIKO_NAMESPACE", "sandman")
PORT = int(os.getenv("HOOK_PORT", "8090"))

def log(msg):
    print(msg, flush=True)
    try:
        with open("/tmp/kaniko-hook.log", "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def pod_name(cr_name):
    safe = re.sub(r"[^a-z0-9-]", "-", cr_name.lower()).strip("-")[:56]
    return f"kaniko-{safe}"


def build_pod(obj):
    """Desired kaniko pod manifest for a KanikoBuild."""
    meta = obj["metadata"]
    spec = obj.get("spec", {})
    name = meta["name"]
    dest = spec.get("destination") or f"{REGISTRY}/{spec.get('image', 'build')}:{spec.get('tag', 'latest')}"
    ctx_b64 = spec["contextBase64"]
    timeout = spec.get("timeoutSeconds", 900)
    pname = pod_name(name)

    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pname,
            "namespace": meta.get("namespace", NAMESPACE),
            "labels": {"app": "kaniko-build", "kanikobuild": name},
        },
        "spec": {
            "restartPolicy": "Never",
            "activeDeadlineSeconds": timeout,
            "initContainers": [{
                "name": "context",
                "image": "busybox:1.36",
                "command": [
                    "sh", "-c",
                    f"mkdir -p /workspace && echo '{ctx_b64}' | base64 -d > /workspace/context.tar.gz "
                    "&& tar tzf /workspace/context.tar.gz >/dev/null",
                ],
                "volumeMounts": [{"name": "ws", "mountPath": "/workspace"}],
            }],
            "containers": [{
                "name": "kaniko",
                "image": "gcr.io/kaniko-project/executor:latest",
                "args": [
                    "--context=tar:///workspace/context.tar.gz",
                    f"--destination={dest}",
                    "--dockerfile=Dockerfile",
                    "--cache=true",
                    "--push-retry=3",
                ],
                "volumeMounts": [{"name": "ws", "mountPath": "/workspace"}],
                "resources": spec.get("resources") or {},
            }],
            "volumes": [{"name": "ws", "emptyDir": {}}],
        },
    }
    auth = spec.get("authSecret")
    if auth:
        pod["spec"]["containers"][0]["volumeMounts"].append(
            {"name": "docker-config", "mountPath": "/kaniko/.docker"})
        pod["spec"]["volumes"].append({
            "name": "docker-config",
            "secret": {"secretName": auth,
                       "items": [{"key": ".dockerconfigjson", "path": "config.json"}]},
        })
    return pod


def pod_status(pname):
    """(phase, message) for a pod; message = failed container log tail."""
    try:
        p = core.read_namespaced_pod(pname, NAMESPACE)
    except k8s.ApiException as e:
        if e.status == 404:
            return None, None  # pod not created yet -> Pending
        raise RuntimeError(f"pod lookup {pname}: {e}")
    phase = p.status.phase
    msg = None
    if phase in ("Failed", "Error", "Unknown"):
        try:
            msg = core.read_namespaced_pod_log(pname, NAMESPACE, tail_lines=25)
        except Exception:
            msg = None
    return phase, msg


def sync(req):
    # metacontroller v2 sends the parent under "parent" (v1 used "object")
    obj = req.get("parent") or req.get("object") or {}
    meta = obj.get("metadata", {})
    if req.get("finalizing"):
        return {"finalized": True}
    name = meta.get("name", "")
    log(f"sync: name={name!r} keys={sorted(obj.keys())} finalizing={req.get('finalizing')}")
    if not name:
        return {"status": {"phase": "Failed", "message": "missing name"}}
    status = obj.get("status", {})
    generation = meta.get("generation", 0)
    # Terminal latch: once the build finished for this spec generation, never
    # re-create the pod (the GC'd pod would otherwise respawn and rebuild).
    if status.get("phase") in ("Succeeded", "Failed") and status.get("observedGeneration") == generation:
        return {"status": status, "children": []}
    pname = pod_name(name)
    try:
        phase, msg = pod_status(pname)
    except RuntimeError as e:
        log(f"pod lookup failed: {e}")
        phase = None
    if phase == "Succeeded":
        return {"status": {"phase": "Succeeded", "pod": pname,
                           "observedGeneration": generation,
                           "completionTime": json_now()}, "children": [build_pod(obj)]}
    if phase in ("Failed", "Error", "Unknown"):
        return {"status": {"phase": "Failed", "pod": pname,
                           "message": (msg or "build failed")[:4000],
                           "observedGeneration": generation,
                           "completionTime": json_now()}, "children": [build_pod(obj)]}
    pod = build_pod(obj)
    if phase == "Running":
        st = {"phase": "Building", "pod": pname}
    else:
        st = {"phase": "Pending", "pod": pname}
    return {"status": st, "children": [pod]}


def json_now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/healthz"):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length))
            resp = sync(req)
            code = 200
        except Exception as e:
            log(f"sync error: {e}")
            resp = {"status": {"phase": "Failed", "message": str(e)[:1000]}}
            code = 500
        body = json.dumps(resp).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()  # dev fallback only
    core = k8s.CoreV1Api()
    log(f"kaniko-build hook on :{PORT} registry={REGISTRY} ns={NAMESPACE} (in-cluster)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

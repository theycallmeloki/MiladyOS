#!/usr/bin/env python3
"""kaniko-submit: build a local context dir in-cluster via KanikoBuild.

The shared submit primitive for the MiladyOS build fabric. Turns a local
directory containing a Dockerfile into a KanikoBuild CR on the cluster;
kaniko builds in a k8s pod and pushes to the registry. Also used by the
sandman `kaniko-builder` transform and woodpecker steps (M2/M3) — keep it
dependency-free (stdlib only; kubectl on PATH or KUBECONFIG set).

Context shipping (see deploy/kaniko/hook.py):
  - small contexts: spec.contextBase64 (inline argv)
  - large contexts: a ConfigMap in the CR namespace + spec.contextConfigMap
    (the hook mounts it; beats the Linux 128KB/arg argv ceiling)

Usage:
  kaniko-submit.py --context DIR --image NAME [--tag TAG] [options]
  kaniko-submit.py --context DIR --destination FULL_REF [options]

Exit codes: 0 built (or already present), 1 build failed, 2 usage error.
"""
import argparse
import base64
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

REGISTRY = os.getenv("KANIKO_REGISTRY", "miladyosregistry.transparentlyrotatableproxy.site")
NAMESPACE = os.getenv("KANIKO_NAMESPACE", "sandman")
INLINE_B64_LIMIT = 90000  # stays well under the ~128KB argv ceiling


def log(msg):
    print(msg, flush=True)


def kubectl(args, check=True):
    cmd = ["kubectl"]
    kc = os.getenv("KUBECONFIG")
    if kc:
        cmd += ["--kubeconfig", kc]
    cmd += args
    log(f"+ {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def sanitize(name):
    return re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")[:48]


def registry_has_tag(registry, image, tag):
    """True if <registry>/<image>:<tag> already exists (skip rebuilds)."""
    url = f"https://{registry}/v2/{image}/tags/list"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            tags = json.load(r).get("tags", [])
        return tag in tags
    except Exception:
        return False  # registry unreachable/unknown -> build anyway (kubectl will surface real errors)


def registry_digest(registry, image, tag):
    """Best-effort digest for the built image; None if not retrievable."""
    url = f"https://{registry}/v2/{image}/manifests/{tag}"
    req = urllib.request.Request(url, method="HEAD", headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.headers.get("Docker-Content-Digest")
    except Exception:
        return None


def tar_context(context_dir):
    """tar.gz the context with Dockerfile at root, honoring .dockerignore."""
    ignore = set()
    di = os.path.join(context_dir, ".dockerignore")
    if os.path.isfile(di):
        with open(di) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ignore.add(line)

    def excluded(rel):
        for pat in ignore:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/**") or fnmatch.fnmatch(rel, "**/" + pat):
                return True
            for part in rel.split("/")[:-1]:
                if fnmatch.fnmatch(part, pat):
                    return True
        return False

    buf = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    buf.close()
    with tarfile.open(buf.name, "w:gz") as tar:
        for root, dirs, files in os.walk(context_dir):
            rel_root = os.path.relpath(root, context_dir)
            for name in files:
                full = os.path.join(root, name)
                rel = name if rel_root == "." else os.path.join(rel_root, name)
                if rel == ".dockerignore" or excluded(rel):
                    continue
                tar.add(full, arcname=rel)
    with open(buf.name, "rb") as f:
        data = f.read()
    os.unlink(buf.name)
    return data


def apply_cr(name, spec, namespace, cm_data=None):
    """Apply optional ConfigMap (big contexts) then the KanikoBuild CR."""
    if cm_data is not None:
        cm_name = f"{name}-ctx"
        cm_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": cm_name, "namespace": namespace},
            "binaryData": {"context.tar.gz": cm_data},
        }, cm_file)
        cm_file.close()
        # Server-side apply: client-side apply stamps a last-applied
        # configuration annotation (whole manifest), so a context CM over
        # ~190KB raw exceeds the 256KB annotation limit and is rejected.
        kubectl(["apply", "--server-side=true", "-f", cm_file.name])
        os.unlink(cm_file.name)
        spec["contextConfigMap"] = cm_name

    cr = {
        "apiVersion": "build.miladyos.io/v1alpha1",
        "kind": "KanikoBuild",
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }
    cr_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(cr, cr_file)
    cr_file.close()
    kubectl(["apply", "--server-side=true", "-f", cr_file.name])
    os.unlink(cr_file.name)


def poll(name, namespace, timeout_seconds):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        r = kubectl(["get", "kanikobuild", name, "-n", namespace,
                     "-o", "jsonpath={.status.phase}~{.status.message}"], check=False)
        out = r.stdout.strip() if r.returncode == 0 else ""
        if not out:
            time.sleep(5)
            continue
        parts = out.split("~", 1)
        phase = parts[0]
        if phase == "Succeeded":
            return True, None
        if phase == "Failed":
            return False, (parts[1] if len(parts) > 1 and parts[1] else "build failed")
        time.sleep(10)
    return False, f"timed out after {timeout_seconds}s"


def main():
    ap = argparse.ArgumentParser(description="Submit a KanikoBuild from a local context dir")
    ap.add_argument("--context", required=True, help="directory containing Dockerfile at root")
    ap.add_argument("--image", help="image repository name")
    ap.add_argument("--tag", default="latest", help="image tag")
    ap.add_argument("--destination", help="full destination ref (overrides --image/--tag)")
    ap.add_argument("--registry", default=REGISTRY, help=f"registry (default {REGISTRY})")
    ap.add_argument("--namespace", default=NAMESPACE, help=f"CR namespace (default {NAMESPACE})")
    ap.add_argument("--name", help="KanikoBuild name (default kb-<image>-<tag>-<timestamp>)")
    ap.add_argument("--no-skip-if-exists", action="store_true", help="always rebuild, even if the tag is in the registry")
    ap.add_argument("--timeout-seconds", type=int, default=1500)
    ap.add_argument("--auth-secret", help="docker-registry secret name for authenticated registries")
    ap.add_argument("--keep-configmap", action="store_true", help="leave the context ConfigMap behind after the build")
    args = ap.parse_args()

    dockerfile = os.path.join(args.context, "Dockerfile")
    if not os.path.isfile(dockerfile):
        log(f"error: no Dockerfile at {dockerfile}")
        return 2
    if not args.destination and not args.image:
        log("error: need --image or --destination")
        return 2

    dest = args.destination or f"{args.registry}/{args.image}:{args.tag}"
    # image component for the registry existence check / digest fetch:
    image_part = args.image or (args.destination.split("/", 1)[1].rsplit(":", 1)[0] if args.destination else None)

    if not args.no_skip_if_exists and image_part and registry_has_tag(args.registry, image_part, args.tag or "latest"):
        log(f"image already in registry ({dest}) — skipping kaniko build")
        return 0

    log(f"packaging context from {args.context}")
    data = tar_context(args.context)
    b64 = base64.b64encode(data).decode()
    log(f"context: {len(data)} bytes raw, {len(b64)} base64")

    tag_part = (args.tag or "latest").lower()
    if args.name:
        name = args.name
    else:
        base = sanitize(args.image or args.destination.split("/", 1)[1].rsplit(":", 1)[0])
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        name = f"kb-{base}-{tag_part}-{ts}"[:56]

    spec = {"destination": dest, "timeoutSeconds": args.timeout_seconds}
    if args.auth_secret:
        spec["authSecret"] = args.auth_secret

    cm_data = None
    if len(b64) <= INLINE_B64_LIMIT:
        spec["contextBase64"] = b64
        log(f"submitting inline-context KanikoBuild {name}")
    else:
        cm_data = b64
        log(f"submitting configmap-context KanikoBuild {name} (configmap {name}-ctx)")

    apply_cr(name, spec, args.namespace, cm_data)

    log(f"waiting for build (timeout {args.timeout_seconds}s)")
    ok, err = poll(name, args.namespace, args.timeout_seconds)
    if not ok:
        log(f"build FAILED: {err}")
        return 1

    digest = registry_digest(args.registry, image_part, args.tag or "latest") if image_part else None
    if digest:
        log(f"build SUCCEEDED: {dest} digest={digest}")
    else:
        log(f"build SUCCEEDED: {dest}")

    if cm_data is not None and not args.keep_configmap:
        kubectl(["delete", "configmap", f"{name}-ctx", "-n", args.namespace, "--ignore-not-found"], check=False)
        log("context configmap cleaned up")
    return 0


if __name__ == "__main__":
    sys.exit(main())

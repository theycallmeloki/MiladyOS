#!/bin/sh
# MiladyOS first-boot — detect GPU and write /etc/milady/gpu.env with the
# container run flags (D8: first-boot install, not baked — kernels mismatch).
# Called from milady-container.service ExecStartPre via ensure-image.
set -e

GPUFILE=/etc/milady/gpu.env

# NVIDIA: container toolkit must be present (installed by gpu-init on demand)
if command -v nvidia-smi >/dev/null 2>&1; then
    printf 'GPU_FLAGS=--gpus all\nGPU_TYPE=nvidia\n' > "$GPUFILE"
    echo "milady-gpu: nvidia detected"
    exit 0
fi

# AMD: kfd + dri passthrough (mirrors install_miladyos.sh ROCm flags)
if [ -e /dev/kfd ] && ls /dev/dri 2>/dev/null | grep -q card; then
    printf 'GPU_FLAGS=--device=/dev/kfd --device=/dev/dri --ipc=host --security-opt seccomp=unconfined --group-add video --group-add render\nGPU_TYPE=amd\n' > "$GPUFILE"
    echo "milady-gpu: amd detected"
    exit 0
fi

# CPU-only
rm -f "$GPUFILE"
echo "milady-gpu: no GPU"
exit 0

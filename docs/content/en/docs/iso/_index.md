---
title: "Install MiladyOS from an ISO"
linkTitle: "ISO Installation"
weight: 5
description: "Download, verify, and install MiladyOS. Choose a desktop, server, or agent role."
---

MiladyOS starts with a Debian 13 live installer. Choose a role, a target disk,
and an operator account, then reboot into your installed system.

[Get the public ISO]({{< relref "/" >}}#download) ·
[ISO source and build tools](https://github.com/theycallmeloki/MiladyOS/tree/main/ISO)

## Before you begin

- Use an **x86_64 (Intel/AMD 64-bit)** computer or virtual machine. The ISO build targets amd64; it is not an ARM image.
- **Back up your target disk. The installer erases the entire selected disk.** It does not offer guided dual boot. For a first look, use a VM with a disposable disk.
- The installer requires a target disk of at least **8 GiB**. This is an installer floor, not a recommended capacity for container images or AI models. Allow substantially more space for your workloads.
- BIOS and UEFI boot are supported by the build. Secure Boot is not a verified path; use a VM or disable it if the image will not boot.
- The public ISO does **not** embed the MiladyOS container image. Server and agent setups need network access to fetch it. GPU drivers and other packages may also require downloads.
- The Sway desktop session is available in current source. The download panel identifies whether the published ISO includes it; older ISOs can provide a standalone desktop role without the graphical session.

## Verify your download

Download the ISO from the [welcome page]({{< relref "/" >}}#download), then expand
**SHA-256 checksum** there. Compare it with the hash of the file you downloaded.
The following commands use the filename of the published release:

{{< iso-verify >}}

On macOS, use `shasum -a 256` in place of `sha256sum`. On Windows PowerShell,
use `Get-FileHash -Algorithm SHA256` followed by the ISO filename. The complete
64-character result must match (letter case does not matter).
If it differs, do not install from that file; download it again.

## Boot and install

1. Write the ISO as a disk image to a USB drive using your preferred image writer. Copying the `.iso` file onto a normal filesystem is not the same operation. Writing the image erases the USB drive, too.
2. Boot that USB from your computer's boot menu, or attach the ISO as optical media to a VM.
3. Follow the text installer: **role → disk → account → confirm → install**. An agent also needs a cluster join token.
4. Check the selected target disk on the confirmation screen. Installation partitions and formats that disk.
5. Reboot when installation finishes, remove the installation media, and sign in using the account you created. First boot assigns a `milady-<id>` hostname unless you supplied one through unattended configuration.

### Desktop

The standalone role leaves K3s and the MiladyOS control-plane container disabled.
In builds that include the new desktop packages, log in at the local console and run:

```sh
startx
```

This starts **Sway on Wayland**, with the MiladyOS wallpaper and a Foot terminal.
It does not start a classic Xorg session. Graphics stay off until you start the session.

| Shortcut | Action |
| --- | --- |
| Super + Enter | Open a terminal |
| Super + D | Open the application launcher |
| Super + Shift + Q | Close the active window |
| Super + Shift + E | Exit Sway |
| Super + 1–9 | Switch workspaces |

Sway needs a graphics device and a local graphical seat. A serial-only terminal
cannot display it. See the [desktop implementation notes](https://github.com/theycallmeloki/MiladyOS/blob/main/ISO/docs/DESKTOP.md)
for VM and graphics troubleshooting.

### Server

Choose **server** for the first cluster node. It initializes the K3s control plane
and starts the MiladyOS container. Give first boot time to fetch the payload if
it was not embedded in the ISO.

Check the host services after logging in:

```sh
sudo systemctl status k3s milady-container --no-pager
sudo k3s kubectl get nodes
```

The node should appear as `Ready`. If it does not, inspect the service logs:

```sh
sudo journalctl -u k3s -u milady-container -b --no-pager
```

Keep the cluster join token private. You will need it when adding an agent.

### Agent

Choose **agent** to join an existing server. Supply its join token when prompted.
LAN discovery uses Avahi; the server must be reachable from the joining machine.
This is a cluster worker role, distinct from an AI assistant running on the system.

```sh
sudo systemctl status k3s-agent milady-container --no-pager
sudo journalctl -u k3s-agent -b --no-pager
```

On the server, run `sudo k3s kubectl get nodes` to confirm the new worker appears.
For the wider infrastructure, continue to [Multi-Node Setup]({{< relref "/docs/multi-node-setup" >}}).

## Try in a VM

Create an x86_64 VM, attach the downloaded ISO, and give it a dedicated virtual disk
with room for the installed system and your workloads. The same disk-erasing
installer runs inside the VM. Use a virtual display if you want to try Sway in a
build that includes it.

For contributors, the repository includes a Docker/QEMU test workflow. From the
repository root, replace `/absolute/path/to/miladyos.iso` with your actual absolute ISO path:

```sh
# Install to a disposable virtual disk.
ISO/qemu-install-test.sh /absolute/path/to/miladyos.iso .trial.qcow2 install

# After installation, boot the installed disk.
ISO/qemu-install-test.sh /absolute/path/to/miladyos.iso .trial.qcow2 boot
```

Review [the script and its prerequisites](https://github.com/theycallmeloki/MiladyOS/blob/main/ISO/qemu-install-test.sh)
before running it. It uses Docker, KVM, and local VNC/serial access.

## Unattended installs

The installer already accepts a configuration volume labelled **`cidata`**
(`milady-join` is also accepted). A file named **`milady.conf`** on that volume
triggers unattended installation. An optional **`authorized_keys`** file provides
the operator's SSH public keys.

**Attaching this configuration can start an installation without another confirmation.**
Set `DISK` explicitly to the intended target and use a disposable VM to validate
it before using real hardware. If omitted, the unattended installer can select
the first eligible disk.

The configuration is parsed as key/value data, never executed as a shell script:

```ini
# Example shape only: replace the disk and password hash before use.
ROLE=desktop
DISK=/dev/vda
USERNAME=milady
PASSWORD_HASH=REPLACE_WITH_YOUR_SHA512_PASSWORD_HASH
HOSTNAME=milady-home
```

For an agent, set `ROLE=agent` and add `JOIN_TOKEN` with your server's token.
Treat this volume as private: it may contain a password hash or cluster credential.
Do not put secrets into kernel boot parameters or a public ISO.

See the [installer configuration reference](https://github.com/theycallmeloki/MiladyOS/blob/main/ISO/docs/TEXT-INSTALLER.md#unattended-miladyauto-or-a-cidata-volume)
for the supported configuration and current behavior.

A website that accepts configuration, creates this volume, and bundles it with
the base ISO is **planned**. This site does not upload or collect configuration yet.

## Building a newer ISO

The [ISO build tree](https://github.com/theycallmeloki/MiladyOS/tree/main/ISO)
contains the Docker-based build scripts and the current desktop implementation.
The [JIT GitHub workflow](https://github.com/theycallmeloki/MiladyOS/actions/workflows/iso-jit.yml)
can create a draft release with a no-payload ISO. A draft is not a public download;
it must be verified and published before the website links to it.

Payload-embedded builds can include the MiladyOS container for loading from disk.
They are larger than GitHub's per-file release-asset limit, so they need a separate
distribution path. See the [build notes](https://github.com/theycallmeloki/MiladyOS/blob/main/ISO/docs/SANDMAN-BUILD.md).

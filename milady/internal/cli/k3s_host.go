package cli

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"strings"
	"time"
)

// Shared host-level plumbing for the k3s commands. Everything here runs on the
// real host (the ISO-installed node), never inside the container.

const (
	k3sServiceUnit  = "k3s.service"
	serverTokenFile = "/var/lib/rancher/k3s/server/node-token"
	agentStateDir   = "/var/lib/rancher/k3s/agent"
	avahiAdvertSrc  = "/usr/share/milady/kubernetes.service.avahi"
	avahiAdvertDst  = "/etc/avahi/services/kubernetes.service"
)

// requireRoot guards the commands that drive systemd and touch k3s state.
func requireRoot(what string) error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("%s must run as root (drives systemd and k3s state)", what)
	}
	return nil
}

// requireMiladyOSNode keeps the commands from acting on a non-MiladyOS host:
// the node helpers are staged by the ISO's firstboot build step.
func requireMiladyOSNode() error {
	if _, err := os.Stat(discoverHelper); err != nil {
		return fmt.Errorf("not a MiladyOS node: %s not found", discoverHelper)
	}
	return nil
}

// discoverMaster asks the node helper (Avahi _kubernetes._tcp) for a master.
func discoverMaster() (string, error) {
	b, err := exec.Command(discoverHelper).Output()
	master := strings.TrimSpace(string(b))
	if err != nil || master == "" {
		return "", fmt.Errorf("no k3s master discovered on the LAN " +
			"(is a server node advertising _kubernetes._tcp?) — pass --master to override")
	}
	return master, nil
}

// tokenFromFiles returns the first join token staged by the operator (never the
// kernel cmdline, which is world-readable in /proc; the installer ignores it).
// Empty when none is staged.
func tokenFromFiles() string {
	if b, err := os.ReadFile(joinTokenFile); err == nil {
		if t := firstLine(string(b)); t != "" {
			return t
		}
	}
	return ""
}

// readServerToken returns this host's own k3s server token, or "" when this
// host is not a server.
func readServerToken() string {
	b, err := os.ReadFile(serverTokenFile)
	if err != nil {
		return ""
	}
	return firstLine(string(b))
}

// primaryIPv4 returns this host's first non-loopback IPv4 address, used to
// render the operator's pairing command for the agents.
func primaryIPv4() string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return ""
	}
	for _, ifc := range ifaces {
		if ifc.Flags&net.FlagUp == 0 || ifc.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := ifc.Addrs()
		if err != nil {
			continue
		}
		for _, a := range addrs {
			ipnet, ok := a.(*net.IPNet)
			if !ok {
				continue
			}
			if ip4 := ipnet.IP.To4(); ip4 != nil {
				return ip4.String()
			}
		}
	}
	return ""
}

// publishMasterAdvert publishes the Avahi _kubernetes._tcp advert so agents can
// discover this host. Servers only — agents must never look like masters.
func publishMasterAdvert() error {
	b, err := os.ReadFile(avahiAdvertSrc)
	if err != nil {
		return fmt.Errorf("avahi advert template missing (%s): %w", avahiAdvertSrc, err)
	}
	if err := os.MkdirAll("/etc/avahi/services", 0o755); err != nil {
		return err
	}
	return os.WriteFile(avahiAdvertDst, b, 0o644)
}

// unpublishMasterAdvert removes the advert (agent/desktop roles).
func unpublishMasterAdvert() { _ = os.Remove(avahiAdvertDst) }

// waitForServerToken polls for the k3s node-token, which is written when the
// API server first initializes (~30-60s on a cold start).
func waitForServerToken(timeout time.Duration) (string, error) {
	deadline := time.Now().Add(timeout)
	for {
		if tok := readServerToken(); tok != "" {
			return tok, nil
		}
		if !time.Now().Before(deadline) {
			return "", fmt.Errorf("k3s server did not write %s within %s", serverTokenFile, timeout)
		}
		time.Sleep(2 * time.Second)
	}
}

// unitActive reports a systemd unit's ActiveState ("active", "inactive", ...).
func unitActive(unit string) string {
	b, err := exec.Command("systemctl", "is-active", unit).Output()
	s := strings.TrimSpace(string(b))
	if s == "" {
		if err != nil {
			return "unknown"
		}
		return "inactive"
	}
	return s
}

// dirExists reports whether path exists and is a directory.
func dirExists(path string) bool {
	fi, err := os.Stat(path)
	return err == nil && fi.IsDir()
}

// filePresent renders a path as "present" / "missing" for `k3s status`.
func filePresent(path string) string {
	if _, err := os.Stat(path); err == nil {
		return "present"
	}
	return "missing"
}

// parseRole extracts ROLE= from /etc/milady/node.conf content. Pure, so the
// role-selection contract is testable without a node.
func parseRole(conf string) string {
	sc := bufio.NewScanner(strings.NewReader(conf))
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if v, ok := strings.CutPrefix(line, "ROLE="); ok {
			return strings.TrimSpace(v)
		}
	}
	return ""
}

// readRole returns this host's persisted role, or "" when unset.
func readRole() string {
	b, err := os.ReadFile(nodeConf)
	if err != nil {
		return ""
	}
	return parseRole(string(b))
}

// promptSecret reads a secret from the terminal without echo when possible.
// The pairing token is the one manual step of the bring-up, so it must not be
// required on argv (world-readable via /proc).
func promptSecret(prompt string) (string, error) {
	fmt.Fprint(os.Stderr, prompt)

	// stty is present on the node; if stdin is not a TTY it fails and we fall
	// back to a plain (visible) read rather than refusing to work.
	echoOff := exec.Command("stty", "-echo")
	echoOff.Stdin = os.Stdin
	if err := echoOff.Run(); err == nil {
		defer func() {
			back := exec.Command("stty", "echo")
			back.Stdin = os.Stdin
			_ = back.Run()
			fmt.Fprintln(os.Stderr)
		}()
	}

	line, err := bufio.NewReader(os.Stdin).ReadString('\n')
	if err != nil && strings.TrimSpace(line) == "" {
		return "", err
	}
	return strings.TrimSpace(line), nil
}

// qrencode renders s as an ANSI QR in the terminal when qrencode is available
// (the ISO ships it; role-detect.sh prints the token the same way).
func qrencode(out io.Writer, s string) {
	c := exec.Command("qrencode", "-t", "ANSIUTF8")
	c.Stdin = strings.NewReader(s)
	c.Stdout = out
	_ = c.Run()
}

package cli

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"

	"github.com/spf13/cobra"
)

// Node paths written by the ISO's firstboot staging (build-in-container.sh
// installs firstboot/*.sh as /usr/local/sbin/milady-<name>).
const (
	discoverHelper = "/usr/local/sbin/milady-discover-master"
	nodeConf       = "/etc/milady/node.conf"
	joinTokenFile  = "/etc/milady/join-token"
	agentDropInDir = "/etc/systemd/system/k3s-agent.service.d"
	agentDropIn    = agentDropInDir + "/milady-join.conf"
	agentUnit      = "k3s-agent.service"
)

// newK3sCmd groups k3s cluster operations that run on the host/ISO, e.g.
// discovering a peer's advertised master and joining it automatically.
func newK3sCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "k3s",
		Short: "k3s cluster operations for the host/ISO",
		Args:  cobra.NoArgs,
		RunE:  func(cmd *cobra.Command, _ []string) error { return cmd.Help() },
	}

	cmd.AddCommand(newK3sJoinCmd())

	return cmd
}

// newK3sJoinCmd discovers a peer-advertised k3s master and joins this host to
// it as an agent, mirroring the agent branch of the ISO's first-boot role
// detection (/usr/local/sbin/milady-role-detect) so an operator can join a
// running node without rebooting it:
//
//  1. discover the master (Avahi _kubernetes._tcp, via the node helper)
//  2. write /etc/systemd/system/k3s-agent.service.d/milady-join.conf
//  3. systemctl daemon-reload && systemctl enable --now k3s-agent
//
// The join token is read from /etc/milady/join-token (the operator-provided
// file the installer copies off a cidata volume) or from --token. It is never
// required on the kernel cmdline (PLAN §Join-token secrecy).
func newK3sJoinCmd() *cobra.Command {
	var master string
	var token string
	var dryRun bool

	cmd := &cobra.Command{
		Use:   "join",
		Short: "Join this host to a k3s cluster (token discovery + registration)",
		Long: "Join this host to a k3s cluster as an agent.\n\n" +
			"The master is discovered over Avahi (_kubernetes._tcp) unless --master\n" +
			"is given; the join token comes from " + joinTokenFile + " unless --token\n" +
			"is given. Requires root (writes a systemd drop-in and drives systemd).",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			out := cmd.OutOrStdout()

			if os.Geteuid() != 0 {
				return fmt.Errorf("k3s join must run as root (writes %s and drives systemd)", agentDropIn)
			}
			if _, err := os.Stat(discoverHelper); err != nil {
				return fmt.Errorf("not a MiladyOS node: %s not found", discoverHelper)
			}

			if master == "" {
				b, err := exec.Command(discoverHelper).Output()
				master = strings.TrimSpace(string(b))
				if err != nil || master == "" {
					return fmt.Errorf("no k3s master discovered on the LAN " +
						"(is a server node advertising _kubernetes._tcp?) — pass --master to override")
				}
			}

			if token == "" {
				if b, err := os.ReadFile(joinTokenFile); err == nil {
					token = firstLine(string(b))
				}
			}

			dropIn := "[Service]\n" +
				fmt.Sprintf("Environment=\"K3S_URL=https://%s:6443\"\n", master)
			if token != "" {
				dropIn += fmt.Sprintf("Environment=\"K3S_TOKEN=%s\"\n", token)
			} else {
				fmt.Fprintf(out, "warning: no join token found (%s or --token); "+
					"the server may reject this agent\n", joinTokenFile)
			}

			fmt.Fprintf(out, "master: %s\ntoken:  %s\n", master, redact(token))

			if dryRun {
				fmt.Fprintf(out, "\n--dry-run: would write %s:\n%s", agentDropIn, dropIn)
				return nil
			}

			if err := os.MkdirAll(agentDropInDir, 0o755); err != nil {
				return err
			}
			if err := os.WriteFile(agentDropIn, []byte(dropIn), 0o644); err != nil {
				return err
			}
			// Persist the role so the next boot rejoins instead of re-deciding.
			if err := persistRole("agent"); err != nil {
				return err
			}

			for _, args := range [][]string{
				{"daemon-reload"},
				{"enable", agentUnit},
				{"--no-block", "start", agentUnit},
			} {
				if err := runSystemctl(out, args...); err != nil {
					return err
				}
			}

			fmt.Fprintf(out, "k3s-agent configured for https://%s:6443\n", master)
			return nil
		},
	}

	cmd.Flags().StringVar(&master, "master", "", "k3s master host/IP (default: Avahi discovery)")
	cmd.Flags().StringVar(&token, "token", "", "join token (default: "+joinTokenFile+")")
	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "show what would change, touch nothing")

	return cmd
}

// persistRole sets ROLE= in /etc/milady/node.conf, preserving other keys —
// the same contract role-detect.sh uses.
func persistRole(role string) error {
	lines := []string{}
	if b, err := os.ReadFile(nodeConf); err == nil {
		sc := bufio.NewScanner(strings.NewReader(string(b)))
		for sc.Scan() {
			if strings.HasPrefix(sc.Text(), "ROLE=") {
				continue
			}
			lines = append(lines, sc.Text())
		}
	}
	lines = append(lines, "ROLE="+role)

	if err := os.MkdirAll("/etc/milady", 0o755); err != nil {
		return err
	}
	return os.WriteFile(nodeConf, []byte(strings.Join(lines, "\n")+"\n"), 0o644)
}

func runSystemctl(out io.Writer, args ...string) error {
	fmt.Fprintf(out, "systemctl %s\n", strings.Join(args, " "))
	c := exec.Command("systemctl", args...)
	c.Stdout, c.Stderr = os.Stdout, os.Stderr
	return c.Run()
}

// firstLine returns s up to (not including) the first newline.
func firstLine(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return strings.TrimSpace(s[:i])
	}
	return strings.TrimSpace(s)
}

// redact hides all but a recognisable suffix of a secret.
func redact(s string) string {
	if s == "" {
		return "(none)"
	}
	if len(s) <= 8 {
		return "****"
	}
	return "…" + s[len(s)-8:]
}

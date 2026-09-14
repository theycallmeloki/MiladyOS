package cli

import (
	"fmt"
	"io"
	"os"
)

// joinAgent configures this host to join a k3s cluster as an agent: write the
// systemd drop-in, persist the role, then reload + enable + start k3s-agent.
//
// Mirrors the agent branch of the ISO's first boot so an operator can join a
// running node without rebooting it. When dryRun is set nothing is written.
func joinAgent(out io.Writer, master, token string, dryRun bool) error {
	if master == "" {
		return fmt.Errorf("k3s join needs a master (--master or Avahi discovery)")
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
}

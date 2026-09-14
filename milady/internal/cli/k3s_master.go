package cli

import (
	"fmt"
	"os"
	"time"

	"github.com/spf13/cobra"
)

// newK3sMasterCmd turns this live host into a k3s control plane (the ISO's
// server role) without rebooting — the counterpart of `milady k3s join`.
//
// It mirrors the server branch of the ISO's first boot
// (/usr/local/sbin/milady-role-detect): purge any agent state, publish the
// Avahi master advert, enable + start k3s (the ISO installs `k3s server
// --docker`, datastore sqlite by default), persist the role, then print the
// pairing invite the operator hands to the agents.
func newK3sMasterCmd() *cobra.Command {
	var dryRun bool
	var wait time.Duration

	cmd := &cobra.Command{
		Use:     "master",
		Aliases: []string{"server", "init"},
		Short:   "Make this host a k3s control plane (server)",
		Long: "Make this host a k3s control plane.\n\n" +
			"Enables and starts k3s in server mode, publishes the LAN advert so agents\n" +
			"can discover it, and prints the pairing invitation an operator hands to\n" +
			"the agents. Requires root.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			out := cmd.OutOrStdout()
			if err := requireRoot("k3s master"); err != nil {
				return err
			}
			if err := requireMiladyOSNode(); err != nil {
				return err
			}

			// Switching from agent: purge agent state so a half-formed agent
			// registration cannot shadow the new server. role-switch.sh does
			// the same teardown for agent -> server.
			fromAgent := unitActive(agentUnit) == "active" || dirExists(agentStateDir)
			if fromAgent {
				fmt.Fprintf(out, "previous agent role detected — stopping %s and purging %s\n",
					agentUnit, agentStateDir)
				if !dryRun {
					_ = runSystemctl(out, "disable", "--now", agentUnit)
					_ = os.RemoveAll(agentStateDir)
					_ = os.RemoveAll(agentDropInDir)
					_ = runSystemctl(out, "daemon-reload")
				}
			}

			if dryRun {
				fmt.Fprintf(out, "\n--dry-run: would\n"+
					"  publish %s\n"+
					"  systemctl enable %s\n"+
					"  systemctl --no-block start %s\n"+
					"  persist ROLE=server in %s\n",
					avahiAdvertDst, k3sServiceUnit, k3sServiceUnit, nodeConf)
				return nil
			}

			if err := publishMasterAdvert(); err != nil {
				return err
			}
			if err := persistRole("server"); err != nil {
				return err
			}
			if err := runSystemctl(out, "enable", k3sServiceUnit); err != nil {
				return err
			}
			// k3s.service is Type=notify with TimeoutStartSec=0, so `enable
			// --now` would block forever waiting for READY=1; start detached
			// and let the token poll below be the wait.
			if err := runSystemctl(out, "--no-block", "start", k3sServiceUnit); err != nil {
				return err
			}

			if wait == 0 {
				fmt.Fprintf(out, "k3s server starting (not waiting for the token)\n")
				return nil
			}
			fmt.Fprintf(out, "waiting up to %s for the k3s API server to initialize…\n", wait)
			token, err := waitForServerToken(wait)
			if err != nil {
				return fmt.Errorf("%w — check: journalctl -u %s", err, k3sServiceUnit)
			}
			printPairingInvite(out, token)
			return nil
		},
	}

	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "show what would change, touch nothing")
	cmd.Flags().DurationVar(&wait, "wait", 5*time.Minute,
		"how long to wait for the join token (0 = don't wait)")
	return cmd
}

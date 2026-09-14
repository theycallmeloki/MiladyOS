package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

// newK3sStatusCmd reports this host's cluster role and k3s state — the quick
// "did the bring-up take?" check after master/join/pair.
func newK3sStatusCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Show this host's k3s role and state",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			out := cmd.OutOrStdout()

			role := readRole()
			if role == "" {
				role = "(unset)"
			}
			fmt.Fprintf(out, "role:          %s\n", role)
			fmt.Fprintf(out, "%-14s %s\n", k3sServiceUnit+":", unitActive(k3sServiceUnit))
			fmt.Fprintf(out, "%-14s %s\n", agentUnit+":", unitActive(agentUnit))
			fmt.Fprintf(out, "master advert: %s (%s)\n", filePresent(avahiAdvertDst), avahiAdvertDst)
			fmt.Fprintf(out, "join token:    %s (%s)\n", filePresent(joinTokenFile), joinTokenFile)
			if tok := readServerToken(); tok != "" {
				fmt.Fprintf(out, "server token:  %s (%s)\n", redact(tok), serverTokenFile)
			}
			return nil
		},
	}
}

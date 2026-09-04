package cli

import "github.com/spf13/cobra"

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

// newK3sJoinCmd will discover a peer-advertised k3s master token and join this
// host to the cluster. Mirrors the manual token discovery done during ISO work.
func newK3sJoinCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "join",
		Short: "Join this host to a k3s cluster (token discovery + registration)",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return notImplemented(cmd)
		},
	}
}

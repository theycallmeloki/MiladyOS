package cli

import (
	"github.com/spf13/cobra"

	"github.com/theycallmeloki/MiladyOS/milady/internal/update"
)

// newUpdateCmd checks the MiladyOS GitHub releases and installs the latest
// build over the running binary when behind (self-update off the release
// assets milady-<os>-<arch> + .sha256).
func newUpdateCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "update",
		Short: "Update milady to the latest release",
		Long:  "Check the MiladyOS GitHub releases and install the latest build over " + "/usr/local/bin/milady when behind. Uses the release assets (milady-<os>-<arch> + .sha256) with checksum verification.",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			checkOnly, _ := cmd.Flags().GetBool("check")
			return update.Run(update.Options{CheckOnly: checkOnly, Out: cmd.OutOrStdout()})
		},
	}
	cmd.Flags().Bool("check", false, "report the latest release without installing")
	return cmd
}

package cli

import "github.com/spf13/cobra"

// newSlurpCmd produces a lean, ignore-honoring build-context tarball from a
// host path and pushes it to the MiladyOS container for building. Handles the
// bare-folder case; git repos ride free by design.
func newSlurpCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "slurp <path>",
		Short: "Package a host folder as a build context for the MiladyOS container",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, _ []string) error {
			return notImplemented(cmd)
		},
	}
}

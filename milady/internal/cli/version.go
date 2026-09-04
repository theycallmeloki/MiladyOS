package cli

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/theycallmeloki/MiladyOS/milady/internal/version"
)

// newVersionCmd prints full build/version detail. The bare --version flag is
// handled by cobra from root.Version.
func newVersionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print milady version information",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			fmt.Fprintln(cmd.OutOrStdout(), version.String())
			return nil
		},
	}
}

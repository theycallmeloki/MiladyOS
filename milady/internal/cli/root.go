// Package cli wires the milady cobra command tree.
package cli

import (
	"github.com/spf13/cobra"

	"github.com/theycallmeloki/MiladyOS/milady/internal/version"
)

// notImplemented marks a registered-but-unbuilt command (`milady ask` is the
// remaining one: it needs the MCP + function-calling loop, not a stub-fix).
func notImplemented(cmd *cobra.Command) error {
	return &NotImplementedError{cmd: cmd}
}

// NotImplementedError is returned by skeleton commands that are wired into the
// tree but whose behavior has not been implemented yet.
type NotImplementedError struct {
	cmd *cobra.Command
}

func (e *NotImplementedError) Error() string {
	return "milady: command '" + e.cmd.Name() + "' is not implemented yet"
}

// NewRootCmd builds the root milady command.
func NewRootCmd() *cobra.Command {
	root := &cobra.Command{
		Use:   "milady",
		Short: "MiladyOS host companion",
		Long: "milady is the host-side companion for the MiladyOS container.\n\n" +
			"It owns operations that must run on the real host (build-context slurp, " +
			"k3s join, self-update) and talks to the MiladyOS container's MCP for " +
			"everything the container owns (ask).",
		SilenceUsage:  true,
		SilenceErrors: true,
		Version:       version.Version,
	}

	// `--version` prints the same banner as `milady version`: the bare
	// version.Version would drop the commit and toolchain a bug report needs.
	root.SetVersionTemplate(version.String() + "\n")

	root.AddCommand(
		newAskCmd(),
		newSlurpCmd(),
		newK3sCmd(),
		newUpdateCmd(),
		newVersionCmd(),
	)

	return root
}

// Execute runs the root command.
func Execute() error {
	return NewRootCmd().Execute()
}

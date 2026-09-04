package cli

import "github.com/spf13/cobra"

// newAskCmd replaces the legacy Python mcp-llm-bridge: drive the MiladyOS MCP
// through an OpenAI-compatible endpoint with function calling.
func newAskCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "ask [prompt]",
		Short: "Send a prompt to milady through the MiladyOS MCP",
		Args:  cobra.ArbitraryArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return notImplemented(cmd)
		},
	}
}

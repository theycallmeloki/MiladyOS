package cli

import (
	"fmt"
	"io"
	"net/url"
	"os"

	"github.com/spf13/cobra"
)

// printPairingInvite renders the operator's handshake material: the token, a
// scannable invite that carries both master and token, and the exact command to
// run on an agent.
func printPairingInvite(out io.Writer, token string) {
	master := primaryIPv4()
	invite := buildInvite(master, token)

	fmt.Fprintf(out, "\ncluster pairing invitation\n")
	fmt.Fprintf(out, "  master: %s\n", master)
	fmt.Fprintf(out, "  token:  %s\n", token)
	fmt.Fprintf(out, "\n  scan:\n")
	qrencode(out, invite)
	fmt.Fprintf(out, "\non each agent node, run:\n  milady k3s pair --invite '%s'\n", invite)
}

// buildInvite encodes master + token into one scannable URI.
func buildInvite(master, token string) string {
	u := url.URL{Scheme: "milady", Host: "pair"}
	q := url.Values{}
	q.Set("master", master)
	q.Set("token", token)
	u.RawQuery = q.Encode()
	return u.String()
}

// parseInvite decodes a pairing URI printed by the master.
func parseInvite(s string) (master, token string, err error) {
	u, err := url.Parse(s)
	if err != nil {
		return "", "", err
	}
	if u.Scheme != "milady" {
		return "", "", fmt.Errorf("not a milady pairing invite (want milady://pair?...): %q", s)
	}
	q := u.Query()
	return q.Get("master"), q.Get("token"), nil
}

// newK3sPairCmd is the operator's pairing step: on a master it prints the
// invitation; on an agent it consumes it and joins. This is the one manual
// handshake of the fleet bring-up — the token is deliberately never copied
// automatically (PLAN §Join-token secrecy).
func newK3sPairCmd() *cobra.Command {
	var master, token, tokenFile, invite string
	var dryRun bool

	cmd := &cobra.Command{
		Use:   "pair",
		Short: "Pair this host with the cluster (operator handshake)",
		Long: "The one manual step of the fleet bring-up: bind an agent host to a\n" +
			"master using the pairing token.\n\n" +
			"On a master it prints the invitation (token + scannable QR). On an agent\n" +
			"pass --invite (as printed, or scanned from the QR), --master plus a\n" +
			"token, or just run it and enter the token when prompted.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			out := cmd.OutOrStdout()
			if err := requireRoot("k3s pair"); err != nil {
				return err
			}
			if err := requireMiladyOSNode(); err != nil {
				return err
			}

			if invite != "" {
				m, t, err := parseInvite(invite)
				if err != nil {
					return err
				}
				if master == "" {
					master = m
				}
				if token == "" {
					token = t
				}
			}

			// Server side: no explicit target and we are the master, so print
			// the invitation instead of trying to join ourselves.
			if master == "" && unitActive(k3sServiceUnit) == "active" {
				tok := readServerToken()
				if tok == "" {
					return fmt.Errorf("this host is a k3s server but %s is not readable yet", serverTokenFile)
				}
				printPairingInvite(out, tok)
				return nil
			}

			// Agent side: consume the invitation.
			if master == "" {
				var err error
				master, err = discoverMaster()
				if err != nil {
					return err
				}
			}
			if token == "" && tokenFile != "" {
				b, err := os.ReadFile(tokenFile)
				if err != nil {
					return err
				}
				token = firstLine(string(b))
			}
			if token == "" {
				token = tokenFromFiles()
			}
			if token == "" {
				var err error
				token, err = promptSecret("pairing token (from the master's invitation): ")
				if err != nil {
					return err
				}
			}
			if token == "" {
				return fmt.Errorf("empty pairing token")
			}
			return joinAgent(out, master, token, dryRun)
		},
	}

	cmd.Flags().StringVar(&invite, "invite", "", "pairing URI printed by the master (milady://pair?...)")
	cmd.Flags().StringVar(&master, "master", "", "master host/IP (default: Avahi discovery)")
	cmd.Flags().StringVar(&token, "token", "", "pairing token (prefer --invite, --token-file or the prompt: argv is world-readable)")
	cmd.Flags().StringVar(&tokenFile, "token-file", "", "read the pairing token from this file")
	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "show what would change, touch nothing")
	return cmd
}

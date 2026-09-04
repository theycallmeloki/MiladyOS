package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/theycallmeloki/MiladyOS/milady/internal/slurp"
)

// newSlurpCmd packages a host folder into a lean, ignore-honoring build
// context tarball for the MiladyOS container. Handles the bare-folder case;
// git repos ride free (git-accurate .gitignore + .dockerignore prune).
func newSlurpCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "slurp <path> [-o out.tar.gz]",
		Short: "Package a host folder as a build context for the MiladyOS container",
		Long: "Package a host folder into a lean, deterministic build-context tar.gz.\n\n" +
			"Ignore rules are applied automatically: git-accurate .gitignore when the\n" +
			"folder is in a repo (tracked + untracked-not-ignored, via git ls-files),\n" +
			"plus the folder's .dockerignore — so caches, venvs, and other huge\n" +
			"untracked trees never enter the context. Docker's own pattern matcher is\n" +
			"used, so a bare folder behaves like docker build.\n\n" +
			"Output goes to stdout by default (pipe it to the MiladyOS upload/build\n" +
			"seam) or to -o FILE.",
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			outPath, _ := cmd.Flags().GetString("output")
			return slurpTo(args[0], outPath, cmd.OutOrStdout(), cmd.ErrOrStderr())
		},
	}
	cmd.Flags().StringP("output", "o", "-", "write the context to FILE instead of stdout ('-' = stdout)")
	return cmd
}

// slurpTo streams the context for root to outPath ("-" = out) and prints a
// summary to errOut.
func slurpTo(root, outPath string, out, errOut io.Writer) error {
	if outPath == "-" {
		// stream raw to stdout; keep the summary on stderr so the pipe is clean
		if err := slurp.Stream(root, out); err != nil {
			return err
		}
		return nil
	}

	abs, err := filepath.Abs(outPath)
	if err != nil {
		return err
	}
	f, err := os.Create(abs)
	if err != nil {
		return err
	}
	if err := slurp.Stream(root, f); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	st, err := os.Stat(abs)
	if err != nil {
		return err
	}
	fmt.Fprintf(errOut, "wrote %s (%d bytes)\n", abs, st.Size())
	return nil
}

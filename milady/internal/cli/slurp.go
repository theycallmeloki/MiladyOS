package cli

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/spf13/cobra"

	"github.com/theycallmeloki/MiladyOS/milady/internal/slurp"
)

// safeName maps a slurped folder path onto a forge-safe job name.
var safeName = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

// newSlurpCmd packages a host folder into a lean, ignore-honoring build
// context tarball for the MiladyOS container. Handles the bare-folder case;
// git repos ride free (git-accurate .gitignore + .dockerignore prune).
func newSlurpCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "slurp <path>",
		Short: "Package a host folder as a build context for the MiladyOS container",
		Long: "Package a host folder into a lean, deterministic build-context tar.gz.\n\n" +
			"Ignore rules are applied automatically: git-accurate .gitignore when the\n" +
			"folder is in a repo (tracked + untracked-not-ignored, via git ls-files),\n" +
			"plus the folder's .dockerignore — so caches, venvs, and other huge\n" +
			"untracked trees never enter the context. Docker's own pattern matcher is\n" +
			"used, so a bare folder behaves like docker build.\n\n" +
			"By default the context streams to stdout (-o -). Pass --push <url> to\n" +
			"POST it to the MiladyOS container's /upload seam as a build-context job\n" +
			"repo instead (name defaults to the folder's basename).",
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			outPath, _ := cmd.Flags().GetString("output")
			pushURL, _ := cmd.Flags().GetString("push")
			name, _ := cmd.Flags().GetString("name")
			if pushURL != "" {
				return slurpPush(args[0], pushURL, name, cmd.ErrOrStderr())
			}
			return slurpTo(args[0], outPath, cmd.OutOrStdout(), cmd.ErrOrStderr())
		},
	}
	cmd.Flags().StringP("output", "o", "-", "write the context to FILE instead of stdout ('-' = stdout)")
	cmd.Flags().String("push", "", "POST the context to URL (MiladyOS /upload seam) instead of writing")
	cmd.Flags().String("name", "", "job name for --push (default: the folder's basename)")
	return cmd
}

// slurpTo streams the context for root to outPath ("-" = out) and prints a
// summary to errOut.
func slurpTo(root, outPath string, out, errOut io.Writer) error {
	if outPath == "-" {
		// stream raw to stdout; keep the summary on stderr so the pipe is clean
		return slurp.Stream(root, out)
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

// slurpPush builds the context for root into a temp file and POSTs it (raw
// gzip body) to url?name=<job>, the container /upload seam.
func slurpPush(root, urlStr, name string, errOut io.Writer) error {
	if name == "" {
		name = jobName(root)
	}
	if !validName(name) {
		return fmt.Errorf("invalid job name %q (alnum, dash, underscore, dot; no leading dot)", name)
	}

	// stream the context to a temp file so we can set Content-Length
	tmp, err := os.CreateTemp("", "milady-slurp-*.tar.gz")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if err := slurp.Stream(root, tmp); err != nil {
		tmp.Close()
		return err
	}
	size, err := tmp.Seek(0, io.SeekEnd)
	if err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Seek(0, io.SeekStart); err != nil {
		tmp.Close()
		return err
	}

	u, err := url.Parse(urlStr)
	if err != nil {
		tmp.Close()
		return fmt.Errorf("parsing --push url: %w", err)
	}
	q := u.Query()
	q.Set("name", name)
	u.RawQuery = q.Encode()

	req, err := http.NewRequest(http.MethodPost, u.String(), tmp)
	if err != nil {
		tmp.Close()
		return err
	}
	req.ContentLength = size
	req.Header.Set("Content-Type", "application/gzip")
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		tmp.Close()
		return fmt.Errorf("push to %s: %w", u.Redacted(), err)
	}
	defer resp.Body.Close()
	tmp.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("push failed: %s %s", resp.Status, strings.TrimSpace(string(body)))
	}
	fmt.Fprintf(errOut, "pushed %s (%d bytes) to %s as job %q\n", root, size, u.Redacted(), name)
	if len(bytes.TrimSpace(body)) > 0 {
		fmt.Fprintf(errOut, "response: %s\n", strings.TrimSpace(string(body)))
	}
	return nil
}

func jobName(root string) string {
	b := filepath.Base(filepath.Clean(root))
	if b == "." || b == "/" || b == "" {
		wd, _ := os.Getwd()
		b = filepath.Base(wd)
	}
	b = strings.TrimPrefix(b, ".")
	b = safeName.ReplaceAllString(b, "-")
	return strings.Trim(b, "-._")
}

func validName(n string) bool {
	if n == "" || strings.HasPrefix(n, ".") {
		return false
	}
	for _, r := range n {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' ||
			r == '-' || r == '_' || r == '.') {
			return false
		}
	}
	return true
}

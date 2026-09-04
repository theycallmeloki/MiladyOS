// Package update implements `milady update`: check the MiladyOS GitHub
// releases for the latest published binary and, when behind, download the
// release asset and install it over the running binary at
// /usr/local/bin/milady.
//
// Releases are tagged 0.0.0.0.<commit-count> (see ISO/version.sh) and carry a
// per-platform binary asset (milady-<os>-<arch>) plus its .sha256. The update
// verifies the checksum before replacing the file (atomic: temp file +
// rename). A non-root install re-executes through sudo when the target
// directory is not writable.
//
// Modeled on theycallmeloki/sandman's update.go; adapted to milady's 5-octet
// (arbitrary-length) version scheme and the MiladyOS release assets.
package update

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/theycallmeloki/MiladyOS/milady/internal/version"
)

const (
	owner = "theycallmeloki"
	repo  = "MiladyOS"

	// installPath is where the production binary lives. Sandman's model: one
	// CLI that updates in place, so a single install updates the whole tool.
	installPath = "/usr/local/bin/milady"
	// binaryName matches the release asset prefix (milady-<os>-<arch>).
	binaryName = "milady"
)

// apiBase is the GitHub API base for release lookups; a package var so tests
// can point it at an httptest server.
var apiBase = "https://api.github.com/repos"

// errNoReleases marks a repo with no published releases yet.
var errNoReleases = errors.New("no releases")

// errReexecInstalled marks that the install delegated to a sudo re-exec whose
// own run printed the result; the caller must not repeat it (the parent would
// otherwise print "updated to …" a second time).
var errReexecInstalled = errors.New("installed via sudo re-exec")

// Options controls a Run.
type Options struct {
	CheckOnly bool // report the latest release without installing
	Out       io.Writer
}

// Run performs `milady update`. current (version.Version) is compared against
// the latest GitHub release; when the current build is not a parseable
// release (e.g. a 0.0.0.0.dev source build) it is treated as behind, so
// `milady update` bootstraps onto the latest release.
func Run(o Options) error {
	out := o.Out
	if out == nil {
		out = os.Stdout
	}

	rel, err := latestRelease()
	if err == errNoReleases {
		fmt.Fprintf(out, "no releases published yet — milady %s is current\n", version.Version)
		return nil
	}
	if err != nil {
		return fmt.Errorf("update: %w", err)
	}

	latest := rel.TagName
	if v, perr := parseVersion(version.Version); perr == nil {
		if lv, lerr := parseVersion(latest); lerr == nil && compareParts(v, lv) >= 0 {
			fmt.Fprintf(out, "milady %s is up to date (latest release: %s)\n", version.Version, latest)
			return nil
		}
	}

	if os.Getenv("MILADY_UPDATE_REEXEC") == "" {
		fmt.Fprintf(out, "new version available: %s (you have %s)\n", latest, version.Version)
	}
	if o.CheckOnly {
		return nil
	}

	asset := assetFor(rel, runtime.GOOS, runtime.GOARCH, "")
	if asset == "" {
		return fmt.Errorf("update: release %s has no %s-%s asset; install from https://github.com/%s/%s/releases", latest, runtime.GOOS, runtime.GOARCH, owner, repo)
	}
	// the sha256 asset must ride the same release
	shasum := assetFor(rel, runtime.GOOS, runtime.GOARCH, ".sha256")
	if shasum == "" {
		return fmt.Errorf("update: release %s is missing the %s checksum asset; refusing unsigned install", latest, runtime.GOOS+"-"+runtime.GOARCH+".sha256")
	}

	if err := installRelease(asset, shasum, installPath); err != nil {
		if err == errReexecInstalled {
			return nil // the sudo re-exec already printed the result
		}
		return fmt.Errorf("update: %w", err)
	}
	fmt.Fprintf(out, "updated to %s — installed at %s\n", latest, installPath)
	return nil
}

// parseVersion splits an octet-dotted version ("0.0.0.0.650", optional "v"
// prefix) into numeric parts. The MiladyOS scheme is arbitrary-length (five
// octets today); unlike semver this treats every segment as numeric.
func parseVersion(s string) ([]int, error) {
	s = strings.TrimPrefix(s, "v")
	parts := strings.Split(s, ".")
	o := make([]int, len(parts))
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil {
			return nil, fmt.Errorf("version %q has non-numeric octet %q", s, p)
		}
		o[i] = n
	}
	if len(o) == 0 {
		return nil, fmt.Errorf("empty version")
	}
	return o, nil
}

// compareParts compares two numeric octet slices; a shorter slice is padded
// with zeros. Returns <0, 0, >0.
func compareParts(a, b []int) int {
	n := len(a)
	if len(b) > n {
		n = len(b)
	}
	for i := 0; i < n; i++ {
		var av, bv int
		if i < len(a) {
			av = a[i]
		}
		if i < len(b) {
			bv = b[i]
		}
		if av != bv {
			return av - bv
		}
	}
	return 0
}

type ghRelease struct {
	TagName string    `json:"tag_name"`
	Assets  []ghAsset `json:"assets"`
}

type ghAsset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
}

// latestRelease fetches the newest tagged release from GitHub.
func latestRelease() (*ghRelease, error) {
	url := fmt.Sprintf("%s/%s/%s/releases/latest", apiBase, owner, repo)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "milady-update/"+version.Version)
	req.Header.Set("Accept", "application/vnd.github+json")
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("checking %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, errNoReleases
	}
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
		return nil, fmt.Errorf("GitHub returned %s: %s", resp.Status, strings.TrimSpace(string(b)))
	}
	var rel ghRelease
	if err := json.NewDecoder(resp.Body).Decode(&rel); err != nil {
		return nil, fmt.Errorf("decoding release: %w", err)
	}
	if rel.TagName == "" {
		return nil, fmt.Errorf("no releases found (repo %s/%s has none yet)", owner, repo)
	}
	return &rel, nil
}

// assetFor finds the asset named milady-<goos>-<goarch>[suffix].
func assetFor(rel *ghRelease, goos, goarch, suffix string) string {
	want := binaryName + "-" + goos + "-" + goarch + suffix
	for _, a := range rel.Assets {
		if a.Name == want {
			return a.BrowserDownloadURL
		}
	}
	return ""
}

// installRelease downloads the binary and its checksum, verifies the hash,
// and atomically replaces the install path (sudo re-exec when the target
// directory is not writable). dst is the install target.
func installRelease(binURL, shaURL, dst string) error {
	tmp, err := os.CreateTemp("", "milady-update-*.bin")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if err := downloadTo(tmp, binURL); err != nil {
		return fmt.Errorf("downloading release: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return err
	}

	sum, err := fetchChecksum(shaURL)
	if err != nil {
		return err
	}
	if err := verifyChecksum(tmpPath, sum); err != nil {
		return err
	}
	if err := os.Chmod(tmpPath, 0o755); err != nil {
		return err
	}

	if err := replaceBinary(tmpPath, dst); err != nil {
		return installAsRoot()
	}
	return nil
}

func downloadTo(w io.Writer, url string) error {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "milady-update/"+version.Version)
	client := &http.Client{Timeout: 10 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("asset download returned %s", resp.Status)
	}
	_, err = io.Copy(w, resp.Body)
	return err
}

// fetchChecksum downloads the milady-<os>-<arch>.sha256 asset and extracts
// the hex digest.
func fetchChecksum(url string) ([]byte, error) {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "milady-update/"+version.Version)
	client := &http.Client{Timeout: time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("checksum download returned %s", resp.Status)
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
	if err != nil {
		return nil, err
	}
	fields := strings.Fields(string(b))
	if len(fields) == 0 {
		return nil, fmt.Errorf("empty checksum file")
	}
	sum, err := hex.DecodeString(fields[0])
	if err != nil {
		return nil, fmt.Errorf("malformed checksum %q", fields[0])
	}
	if len(sum) != sha256.Size {
		return nil, fmt.Errorf("checksum has %d bytes, want %d", len(sum), sha256.Size)
	}
	return sum, nil
}

func verifyChecksum(path string, want []byte) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return err
	}
	if got := h.Sum(nil); !strings.EqualFold(hex.EncodeToString(got), hex.EncodeToString(want)) {
		return fmt.Errorf("checksum mismatch — downloaded binary does not match the release checksum")
	}
	return nil
}

// replaceBinary atomically swaps the downloaded binary over dst.
func replaceBinary(src, dst string) error {
	dir := filepath.Dir(dst)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	staged := dst + ".new"
	if err := os.WriteFile(staged, data, 0o755); err != nil {
		return err
	}
	if err := os.Rename(staged, dst); err != nil {
		os.Remove(staged) // do not leave a half-written binary behind
		return err
	}
	return nil
}

// installAsRoot re-executes the same update through sudo (the target
// directory is root-owned). The check passes again under root; the install
// then succeeds. os.Args[1:] is the original verb + flags. The re-exec sets
// MILADY_UPDATE_REEXEC so the child's run does not repeat the "new version
// available" line the parent already printed.
func installAsRoot() error {
	self := os.Args[0]
	if !strings.Contains(self, "/") {
		if p, err := exec.LookPath(self); err == nil {
			self = p
		}
	}
	cmd := exec.Command("sudo", append([]string{"-p", "sudo password: ", self}, os.Args[1:]...)...)
	cmd.Env = append(os.Environ(), "MILADY_UPDATE_REEXEC=1")
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return fmt.Errorf("could not write %s (permission denied) and sudo failed (exit %d) — run `sudo %s %s`", installPath, ee.ExitCode(), self, strings.Join(os.Args[1:], " "))
		}
		return err
	}
	return errReexecInstalled
}

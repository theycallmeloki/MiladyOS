package slurp

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// writeTree creates files/dirs under root.
func writeTree(t *testing.T, root string, files map[string]string) {
	t.Helper()
	for rel, body := range files {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func tarNames(t *testing.T, data []byte) []string {
	t.Helper()
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	tr := tar.NewReader(gz)
	var names []string
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		names = append(names, hdr.Name)
	}
	return names
}

func git(t *testing.T, dir string, args ...string) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not available")
	}
	c := append([]string{"-C", dir}, args...)
	out, err := exec.Command("git", c...).CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v: %s", args, err, out)
	}
}

func TestBareFolderWalkAndDockerignore(t *testing.T) {
	root := t.TempDir()
	writeTree(t, root, map[string]string{
		"Dockerfile":    "FROM scratch",
		"main.py":       "print(1)",
		"src/mod.py":    "mod",
		"big/keep":      "k",
		".dockerignore": "big/\n!big/keep\n",
	})
	if err := os.WriteFile(filepath.Join(root, "big", "cache.bin"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}

	rels, err := FileList(root)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]bool{}
	for _, r := range rels {
		got[r] = true
	}
	if got[".dockerignore"] {
		t.Errorf(".dockerignore should not ship, got %v", rels)
	}
	for _, want := range []string{"Dockerfile", "main.py", "src/mod.py", "big/keep"} {
		if !got[want] {
			t.Errorf("missing %s: %v", want, rels)
		}
	}
	if got["big/cache.bin"] {
		t.Errorf("big/ pruned by dockerignore but present: %v", rels)
	}
	if !sort.StringsAreSorted(rels) {
		t.Errorf("FileList not sorted: %v", rels)
	}
}

func TestDeterministicBytes(t *testing.T) {
	root := t.TempDir()
	writeTree(t, root, map[string]string{"Dockerfile": "FROM scratch", "a/b.txt": "hi"})
	if err := os.Chmod(filepath.Join(root, "a", "b.txt"), 0o755); err != nil {
		t.Fatal(err)
	}
	var b1, b2 bytes.Buffer
	for _, b := range []*bytes.Buffer{&b1, &b2} {
		if err := Stream(root, b); err != nil {
			t.Fatal(err)
		}
	}
	if !bytes.Equal(b1.Bytes(), b2.Bytes()) {
		t.Fatalf("Stream output not deterministic across runs")
	}
}

func TestSymlinkShippedAsLink(t *testing.T) {
	root := t.TempDir()
	writeTree(t, root, map[string]string{"real.txt": "content"})
	if err := os.Symlink("real.txt", filepath.Join(root, "link.txt")); err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := Stream(root, &buf); err != nil {
		t.Fatal(err)
	}
	names := tarNames(t, buf.Bytes())
	found := false
	for _, n := range names {
		if n == "link.txt" {
			found = true
		}
	}
	if !found {
		t.Fatalf("link.txt missing from tar: %v", names)
	}
	// and Stream still succeeds reading the real file too
	if !stringsContains(names, "real.txt") {
		t.Fatalf("real.txt missing from tar: %v", names)
	}
}

func stringsContains(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}

// TestGitRepoUsesGitIgnore verifies a git work tree's ignored bloat is
// excluded via git (the 77GB case) while untracked-not-ignored is kept.
func TestGitRepoUsesGitIgnore(t *testing.T) {
	root := t.TempDir()
	writeTree(t, root, map[string]string{
		"tracked.txt": "t",
		".gitignore":  "huge/\n",
	})
	git(t, root, "init", "-q")
	git(t, root, "config", "user.email", "t@t")
	git(t, root, "config", "user.name", "t")
	git(t, root, "add", "tracked.txt", ".gitignore")
	git(t, root, "commit", "-qm", "init")
	// ignored huge tree + untracked-not-ignored new file
	writeTree(t, root, map[string]string{
		"huge/cache.bin": strings.Repeat("x", 1000),
		"new.txt":        "n",
	})

	rels, err := FileList(root)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]bool{}
	for _, r := range rels {
		got[r] = true
	}
	if !got["tracked.txt"] {
		t.Errorf("tracked file missing: %v", rels)
	}
	if got["huge/cache.bin"] {
		t.Errorf("git-ignored huge file leaked into context: %v", rels)
	}
	if !got["new.txt"] {
		t.Errorf("untracked-not-ignored file should be included: %v", rels)
	}
}

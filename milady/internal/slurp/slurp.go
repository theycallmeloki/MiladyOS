// Package slurp packages a host folder into a lean, deterministic build
// context tarball for the MiladyOS container.
//
// The file set is chosen so huge untracked trees (caches, venvs, training
// artifacts) never leak into a build:
//
//   - When the folder is inside a git work tree, the set comes from
//     `git ls-files -co --exclude-standard` — git's own, authoritative
//     .gitignore handling (tracked files + untracked-but-not-ignored), which
//     is exactly the "project surface". Git repos "ride free": the ignored
//     bloat is excluded by the same rules that keep it out of git.
//   - A bare folder (no repo) falls back to walking the tree.
//
// The candidate set is then pruned by the folder's .dockerignore (gitignore
// syntax) via moby/patternmatcher, the same engine Docker uses. Output is a
// gzip tar stream: entries sorted by name, normalized ownership, zeroed
// mtimes — deterministic bytes for a given tree.
package slurp

import (
	"archive/tar"
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/moby/patternmatcher"
)

// ErrNotDir marks a slurp path that is not a directory.
var ErrNotDir = errors.New("slurp path is not a directory")

// metaRel is the set of repo/build-meta entries never shipped in a context
// (mirrors Docker, which strips .dockerignore and never wants .git).
func isMeta(rel string) bool {
	if rel == ".dockerignore" || rel == ".gitignore" || rel == ".gitmodules" || rel == ".git" {
		return true
	}
	return strings.HasPrefix(rel, ".git/")
}

// FileList returns the context-relative (slash-delimited) paths under root
// that form the build context, sorted.
func FileList(root string) ([]string, error) {
	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	fi, err := os.Stat(abs)
	if err != nil {
		return nil, err
	}
	if !fi.IsDir() {
		return nil, fmt.Errorf("%w: %s", ErrNotDir, abs)
	}

	rels, ok := gitFiles(abs)
	if !ok {
		rels, err = walkFiles(abs)
		if err != nil {
			return nil, err
		}
	}

	rels, err = applyDockerignore(abs, rels)
	if err != nil {
		return nil, err
	}

	kept := rels[:0]
	for _, r := range rels {
		if !isMeta(r) {
			kept = append(kept, r)
		}
	}
	sort.Strings(kept)
	return kept, nil
}

// gitFiles sources the file set from git when root is inside a work tree.
// Returns ok=false when root is not in a repo (caller should fall back).
func gitFiles(root string) ([]string, bool) {
	cmd := exec.Command("git", "ls-files", "-co", "--exclude-standard", "-z", "--", ".")
	cmd.Dir = root
	out, err := cmd.Output()
	if err != nil {
		return nil, false
	}
	var rels []string
	for _, f := range strings.Split(string(out), "\x00") {
		if f == "" {
			continue
		}
		rels = append(rels, filepath.ToSlash(f))
	}
	return rels, true
}

// walkFiles enumerates every file/symlink under root (bare-folder fallback).
func walkFiles(root string) ([]string, error) {
	var rels []string
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if p == root {
			return nil
		}
		if d.IsDir() {
			if d.Name() == ".git" {
				return filepath.SkipDir
			}
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 || d.Type().IsRegular() {
			rel, rerr := filepath.Rel(root, p)
			if rerr != nil {
				return rerr
			}
			rels = append(rels, filepath.ToSlash(rel))
		}
		return nil
	})
	return rels, err
}

// applyDockerignore prunes rels by root/.dockerignore (gitignore syntax) when
// present, using Docker's own pattern matcher.
func applyDockerignore(root string, rels []string) ([]string, error) {
	data, err := os.ReadFile(filepath.Join(root, ".dockerignore"))
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return rels, nil
		}
		return nil, err
	}
	var patterns []string
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		patterns = append(patterns, line)
	}
	if len(patterns) == 0 {
		return rels, nil
	}
	pm, err := patternmatcher.New(patterns)
	if err != nil {
		return nil, fmt.Errorf("parsing .dockerignore: %w", err)
	}
	kept := make([]string, 0, len(rels))
	for _, r := range rels {
		m, err := pm.MatchesOrParentMatches(r)
		if err != nil {
			return nil, err
		}
		if !m {
			kept = append(kept, r)
		}
	}
	return kept, nil
}

// Stream writes a deterministic gzip tar of the root's build context to w.
func Stream(root string, w io.Writer) error {
	rels, err := FileList(root)
	if err != nil {
		return err
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return err
	}

	gz, err := gzip.NewWriterLevel(w, gzip.BestCompression)
	if err != nil {
		return err
	}
	gz.Header.OS = 0 // deterministic: no host OS byte, no mtime (zero header)
	tw := tar.NewWriter(gz)

	for _, rel := range rels {
		if err := writeEntry(tw, filepath.Join(abs, filepath.FromSlash(rel)), rel); err != nil {
			tw.Close()
			gz.Close()
			return err
		}
	}
	if err := tw.Close(); err != nil {
		gz.Close()
		return err
	}
	return gz.Close()
}

// writeEntry adds one path to the tar with normalized metadata (uid/gid 0,
// zeroed mtime) so output is byte-deterministic.
func writeEntry(tw *tar.Writer, hostPath, name string) error {
	info, err := os.Lstat(hostPath)
	if err != nil {
		return err
	}
	hdr := &tar.Header{
		Name:       name,
		ModTime:    time.Time{}, // zero: deterministic
		AccessTime: time.Time{},
		ChangeTime: time.Time{},
		Uid:        0,
		Gid:        0,
		Uname:      "",
		Gname:      "",
		Format:     tar.FormatPAX,
	}
	mode := info.Mode()
	if mode&os.ModeSymlink != 0 {
		target, err := os.Readlink(hostPath)
		if err != nil {
			return err
		}
		hdr.Typeflag = tar.TypeSymlink
		hdr.Linkname = target
		hdr.Mode = 0o777
		return tw.WriteHeader(hdr)
	}
	if !mode.IsRegular() {
		return nil // skip devices/sockets/fifos
	}
	hdr.Typeflag = tar.TypeReg
	hdr.Size = info.Size()
	// executable bit only
	hdr.Mode = 0o644
	if mode&0o111 != 0 {
		hdr.Mode = 0o755
	}
	if err := tw.WriteHeader(hdr); err != nil {
		return err
	}
	f, err := os.Open(hostPath)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(tw, f)
	return err
}

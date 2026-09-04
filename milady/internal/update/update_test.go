package update

// Unit tests for the self-update path (update.go): 5-octet version
// comparison, checksum verification, release/asset parsing, and the
// end-to-end install against an httptest server. The install target is a
// temp dir — installPath (/usr/local/bin/milady) is never touched.

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseVersion(t *testing.T) {
	if o, err := parseVersion("0.0.0.0.650"); err != nil || len(o) != 5 || o[4] != 650 {
		t.Fatalf("parseVersion(0.0.0.0.650) = %v, %v", o, err)
	}
	if o, err := parseVersion("0.0.0.0.dev"); err == nil {
		t.Fatalf("parseVersion(0.0.0.0.dev): want error, got %v", o)
	}
	if _, err := parseVersion(""); err == nil {
		t.Fatalf("parseVersion(\"\"): want error")
	}
	if _, err := parseVersion("v1.2.3.4"); err != nil {
		t.Fatalf("parseVersion(v1.2.3.4): v prefix should be tolerated: %v", err)
	}
}

func TestCompareParts(t *testing.T) {
	cases := []struct {
		a, b string
		want int // sign
	}{
		{"0.0.0.0.650", "0.0.0.0.650", 0},
		{"0.0.0.0.650", "0.0.0.0.651", -1},
		{"0.0.0.0.651", "0.0.0.0.650", 1},
		{"0.0.0.0.9", "0.0.0.0.10", -1}, // octet compare, not semver
		{"1.0.0.0.0", "0.9.9.9.9", 1},
		{"0.0.0.0.650", "0.0.0.0", 1}, // longer-with-nonzero beats prefix
		{"0.0.0.0", "0.0.0.0.650", -1},
	}
	for _, c := range cases {
		ao, aerr := parseVersion(c.a)
		bo, berr := parseVersion(c.b)
		if aerr != nil || berr != nil {
			t.Fatalf("bad test case %q/%q: %v/%v", c.a, c.b, aerr, berr)
		}
		got := compareParts(ao, bo)
		if (got < 0) != (c.want < 0) || (got > 0) != (c.want > 0) || (got == 0) != (c.want == 0) {
			t.Errorf("compareParts(%q, %q) = %d, want sign %d", c.a, c.b, got, c.want)
		}
	}
}

func TestAssetFor(t *testing.T) {
	rel := &ghRelease{Assets: []ghAsset{
		{Name: "milady-linux-amd64", BrowserDownloadURL: "u1"},
		{Name: "milady-linux-amd64.sha256", BrowserDownloadURL: "u2"},
	}}
	if got := assetFor(rel, "linux", "amd64", ""); got != "u1" {
		t.Fatalf("assetFor linux/amd64 = %q, want u1", got)
	}
	if got := assetFor(rel, "linux", "amd64", ".sha256"); got != "u2" {
		t.Fatalf("assetFor linux/amd64.sha256 = %q, want u2", got)
	}
	if got := assetFor(rel, "linux", "arm64", ""); got != "" {
		t.Fatalf("assetFor linux/arm64 = %q, want empty", got)
	}
}

// fakeRelease server: serves /releases/latest with the given tag+assets and
// /asset/<name> with the given payload (or the sha256 sidecar computed from
// it). Returns a handler closing over the computed checksum.
func fakeRelease(t *testing.T, tag string, binName string, bin []byte, wantHash *string) http.Handler {
	sum := sha256.Sum256(bin)
	hexSum := hex.EncodeToString(sum[:])
	if wantHash != nil {
		*wantHash = hexSum
	}
	mux := http.NewServeMux()
	// apiBase is set to the httptest server URL in the e2e test; latestRelease
	// appends owner/repo, so the mux path is /theycallmeloki/MiladyOS/...
	mux.HandleFunc("/theycallmeloki/MiladyOS/releases/latest", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"tag_name":"`+tag+`","assets":[`+
			`{"name":"`+binName+`","browser_download_url":"`+serverBase(t)+`/asset/`+binName+`"},`+
			`{"name":"`+binName+`.sha256","browser_download_url":"`+serverBase(t)+`/asset/`+binName+`.sha256"}]}`)
	})
	mux.HandleFunc("/asset/", func(w http.ResponseWriter, r *http.Request) {
		name := strings.TrimPrefix(r.URL.Path, "/asset/")
		if strings.HasSuffix(name, ".sha256") {
			io.WriteString(w, hexSum+"  "+name)
			return
		}
		w.Write(bin)
	})
	return mux
}

// serverBase is replaced by httptest's URL at server start; we pass it via a
// package closure below.
var serverBase = func(t *testing.T) string { return "" }

func TestInstallReleaseEndToEnd(t *testing.T) {
	bin := []byte("#!/bin/sh\necho fake milady\n")
	var hexSum string
	handler := fakeRelease(t, "0.0.0.0.999", "milady-linux-amd64", bin, &hexSum)

	var base string
	srv := httptest.NewServer(handler)
	defer srv.Close()
	base = srv.URL
	serverBase = func(t *testing.T) string { return base }

	oldBase := apiBase
	apiBase = srv.URL
	defer func() { apiBase = oldBase }()

	rel, err := latestRelease()
	if err != nil {
		t.Fatalf("latestRelease: %v", err)
	}
	if rel.TagName != "0.0.0.0.999" {
		t.Fatalf("tag = %q, want 0.0.0.0.999", rel.TagName)
	}
	asset := assetFor(rel, "linux", "amd64", "")
	sha := assetFor(rel, "linux", "amd64", ".sha256")
	if asset == "" || sha == "" {
		t.Fatalf("missing assets: bin=%q sha=%q", asset, sha)
	}

	dst := filepath.Join(t.TempDir(), "milady")
	if err := installRelease(asset, sha, dst); err != nil {
		t.Fatalf("installRelease: %v", err)
	}
	got, err := os.ReadFile(dst)
	if err != nil {
		t.Fatalf("read installed: %v", err)
	}
	if string(got) != string(bin) {
		t.Fatalf("installed content mismatch")
	}
}

func TestVerifyChecksumMismatch(t *testing.T) {
	f := filepath.Join(t.TempDir(), "b")
	if err := os.WriteFile(f, []byte("payload"), 0o755); err != nil {
		t.Fatal(err)
	}
	wrong := make([]byte, sha256.Size)
	if err := verifyChecksum(f, wrong); err == nil {
		t.Fatalf("verifyChecksum: want mismatch error")
	}
}

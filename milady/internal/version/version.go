// Package version holds build-time version metadata.
//
// Version follows the MiladyOS 5-octet scheme: MAJOR.MINOR.PATCH.BUILD.COMMIT,
// e.g. "0.0.0.0.562". The first four octets come from version.json at the repo
// root (the manual source of truth); the fifth is the monotonic git commit
// count (git rev-list --count HEAD). Deriving the full string from version.json
// + commit count is a build/release step (a CI workflow concern), and the
// result is injected at build time via ldflags, e.g.:
//
//	VERSION="$(jq -r .version version.json).$(git rev-list --count HEAD)"
//	go build -ldflags \
//	  "-X github.com/theycallmeloki/MiladyOS/milady/internal/version.Version=$VERSION \
//	   -X github.com/theycallmeloki/MiladyOS/milady/internal/version.Commit=$(git rev-parse HEAD)" \
//	  ./cmd/milady
package version

import "runtime"

var (
	// Version is the release tag, defaulting to a dev marker.
	Version = "0.0.0.0.dev"
	// Commit is the full source commit the binary was built from.
	Commit = "unknown"
)

// String renders the full version banner.
func String() string {
	return "milady " + Version + "\ncommit: " + Commit + "\ngo: " + runtime.Version()
}

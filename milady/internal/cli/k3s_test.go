package cli

import (
	"bytes"
	"strings"
	"testing"
)

func TestParseRole(t *testing.T) {
	cases := []struct {
		name string
		conf string
		want string
	}{
		{"plain", "ROLE=server\n", "server"},
		{"with other keys", "HOSTNAME=milady-10001\nROLE=agent\n", "agent"},
		{"role last", "ROLE=desktop", "desktop"},
		{"unset", "HOSTNAME=milady-10001\n", ""},
		{"empty", "", ""},
		{"whitespace", "  ROLE=server  \n", "server"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := parseRole(tc.conf); got != tc.want {
				t.Fatalf("parseRole(%q) = %q, want %q", tc.conf, got, tc.want)
			}
		})
	}
}

func TestJoinAgentDryRunWritesNothing(t *testing.T) {
	var out bytes.Buffer
	// dryRun must never touch the filesystem (the real path writes a systemd
	// drop-in and drives systemd, which a unit test must not do).
	err := joinAgent(&out, "192.168.1.10", "K10abc::server:def", true)
	if err != nil {
		t.Fatalf("joinAgent dry-run: %v", err)
	}
	got := out.String()
	for _, want := range []string{
		"master: 192.168.1.10",
		"K3S_URL=https://192.168.1.10:6443",
		"K3S_TOKEN=K10abc::server:def",
		agentDropIn,
	} {
		if !strings.Contains(got, want) {
			t.Errorf("dry-run output missing %q\n---\n%s", want, got)
		}
	}
}

func TestJoinAgentRequiresMaster(t *testing.T) {
	var out bytes.Buffer
	if err := joinAgent(&out, "", "tok", true); err == nil {
		t.Fatal("expected an error when no master is given")
	}
}

func TestInviteRoundTrip(t *testing.T) {
	// Tokens contain colons and the invite is URL-encoded, so exercise a real
	// k3s-style token rather than a toy string.
	const master = "192.168.1.10"
	const token = "K10abcdef0123456789::server:9f8e7d6c5b4a"

	m, tok, err := parseInvite(buildInvite(master, token))
	if err != nil {
		t.Fatalf("parseInvite: %v", err)
	}
	if m != master {
		t.Errorf("master = %q, want %q", m, master)
	}
	if tok != token {
		t.Errorf("token = %q, want %q", tok, token)
	}
}

func TestParseInviteRejectsForeignScheme(t *testing.T) {
	if _, _, err := parseInvite("https://example.com/?master=x&token=y"); err == nil {
		t.Fatal("expected an error for a non-milady invite URI")
	}
}

func TestPrintPairingInvite(t *testing.T) {
	var out bytes.Buffer
	printPairingInvite(&out, "K10abc::server:def")
	got := out.String()

	for _, want := range []string{
		"cluster pairing invitation",
		"K10abc::server:def",
		"milady k3s pair --invite 'milady://pair?",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("invite missing %q\n---\n%s", want, got)
		}
	}

	// The invite in the printed command must round-trip back to the token.
	start := strings.Index(got, "milady://pair?")
	end := strings.Index(got[start:], "'")
	if start < 0 || end < 0 {
		t.Fatalf("no parseable invite URI in output:\n%s", got)
	}
	_, tok, err := parseInvite(got[start : start+end])
	if err != nil {
		t.Fatalf("printed invite does not parse: %v", err)
	}
	if tok != "K10abc::server:def" {
		t.Fatalf("invite token = %q, want the printed token", tok)
	}
}

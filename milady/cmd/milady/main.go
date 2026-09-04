// Command milady is the MiladyOS host companion.
package main

import (
	"fmt"
	"os"

	"github.com/theycallmeloki/MiladyOS/milady/internal/cli"
)

func main() {
	if err := cli.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// codeview prints a cut-down view of C# and TypeScript files for AI readers, and
// benchmarks the cut on real repos. See ../README.md.
package main

import (
	"fmt"
	"os"
	"strings"
)

func main() {
	if len(os.Args) < 3 {
		usage()
	}
	switch os.Args[1] {
	case "view":
		args := os.Args[2:]
		numbers := true
		if args[0] == "--no-numbers" {
			numbers, args = false, args[1:]
		}
		if len(args) != 1 {
			usage()
		}
		src, err := os.ReadFile(args[0])
		check(err)
		lang, ok := LangOf(args[0])
		if !ok {
			fatal("unsupported file type: " + args[0])
		}
		v, err := View(src, lang, Options{Numbers: numbers})
		check(err)
		fmt.Print(v)
	case "bench":
		bench(os.Args[2:])
	default:
		usage()
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: codeview view [--no-numbers] FILE\n       codeview bench REPO_DIR...")
	os.Exit(2)
}

func check(err error) {
	if err != nil {
		fatal(err.Error())
	}
}

func fatal(msg string) {
	fmt.Fprintln(os.Stderr, "codeview:", strings.TrimSpace(msg))
	os.Exit(1)
}

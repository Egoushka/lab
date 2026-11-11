package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type agg struct {
	files, unparsed, perfect    int
	bytesIn, bytesView          int
	b4In, b4View, b4ViewNoNum   int
	pcIn, pcView, pcViewNoNum   int
	symOrig, symFound, symExtra int
	gutOK, gutTotal, sigBreaks  int
	elapsed                     time.Duration
}

func (a *agg) pct(in, out int) float64 {
	if in == 0 {
		return 0
	}
	return 100 * float64(out) / float64(in)
}

func bench(repos []string) {
	fmt.Println("| Repo | Lang | Files | Unparsed | Bytes kept | Tokens kept (pieces) | Tokens kept (bytes/4) | Tokens kept, no gutter (pieces) | Symbols | Found in view | Exact files | Cut signatures |")
	fmt.Println("|---|---|---|---|---|---|---|---|---|---|---|---|")
	for _, repo := range repos {
		out, err := exec.Command("git", "-C", repo, "ls-files", "-z").Output()
		check(err)
		per := map[Lang]*agg{CSharp: {}, TypeScript: {}}
		for _, rel := range strings.Split(string(out), "\x00") {
			lang, ok := LangOf(rel)
			if !ok || strings.Contains(rel, ".min.") {
				continue
			}
			p := filepath.Join(repo, rel)
			if fi, err := os.Stat(p); err != nil || !fi.Mode().IsRegular() || fi.Size() > 2<<20 {
				continue
			}
			src, err := os.ReadFile(p)
			if err != nil {
				continue
			}
			a := per[lang]
			a.files++
			t0 := time.Now()
			vn, err := View(src, lang, Options{Numbers: true})
			a.elapsed += time.Since(t0)
			if err != nil { // lexer miss: count it and charge the full file
				a.unparsed++
				addTokens(a, string(src), string(src), string(src), len(src))
				continue
			}
			v0, _ := View(src, lang, Options{Numbers: false})
			addTokens(a, string(src), vn, v0, len(src))
			orig := SymbolsOfSource(src, lang)
			got := SymbolsOfView(vn, lang)
			set := map[Symbol]bool{}
			for _, s := range got {
				set[s] = true
			}
			missing := 0
			for _, s := range orig {
				if set[s] {
					a.symFound++
				} else {
					missing++
				}
			}
			a.symOrig += len(orig)
			a.symExtra += len(got) - (len(orig) - missing)
			if missing == 0 && len(got) == len(orig) {
				a.perfect++
			}
			ok2, tot := GutterFaithful(src, vn)
			a.gutOK += ok2
			a.gutTotal += tot
			a.sigBreaks += SignatureBreaks(vn, lang)
		}
		for _, l := range []Lang{CSharp, TypeScript} {
			a := per[l]
			if a.files == 0 {
				continue
			}
			name := map[Lang]string{CSharp: "C#", TypeScript: "TS"}[l]
			fmt.Printf("| %s | %s | %d | %d | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %d | %.2f%% | %.1f%% | %d |\n",
				filepath.Base(repo), name, a.files, a.unparsed,
				a.pct(a.bytesIn, a.bytesView), a.pct(a.pcIn, a.pcView), a.pct(a.b4In, a.b4View), a.pct(a.pcIn, a.pcViewNoNum),
				a.symOrig, 100*float64(a.symFound)/float64(max(a.symOrig, 1)), a.pct(a.files-a.unparsed, a.perfect), a.sigBreaks)
			fmt.Fprintf(os.Stderr, "%s %s: gutter lines faithful %d/%d, extra symbols in view %d, view time %s\n",
				filepath.Base(repo), name, a.gutOK, a.gutTotal, a.symExtra, a.elapsed.Round(time.Millisecond))
		}
	}
}

func addTokens(a *agg, orig, view, viewNoNum string, n int) {
	a.bytesIn += n
	a.bytesView += len(view)
	a.b4In += TokensBytes4(orig)
	a.b4View += TokensBytes4(view)
	a.b4ViewNoNum += TokensBytes4(viewNoNum)
	a.pcIn += TokensPieces(orig)
	a.pcView += TokensPieces(view)
	a.pcViewNoNum += TokensPieces(viewNoNum)
}

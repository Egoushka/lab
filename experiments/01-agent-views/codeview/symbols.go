package main

import (
	"regexp"
	"strconv"
	"strings"
)

// Symbol is a public declaration found by a model-free line scan.
type Symbol struct {
	Name string
	Line int
}

var (
	csMods  = regexp.MustCompile(`^\s*(?:\[[^\]]*\]\s*)*((?:(?:public|protected|internal|private|static|abstract|sealed|virtual|override|partial|readonly|async|new|unsafe|extern|required|file|const|volatile)\s+)+)(.*)$`)
	csType  = regexp.MustCompile(`^(?:class|struct|interface|enum|record(?:\s+(?:class|struct))?)\s+(\w+)`)
	csDeleg = regexp.MustCompile(`^delegate\s+[^(]*?(\w+)\s*(?:<[^()]*>)?\s*\(`)
	tsExp   = regexp.MustCompile(`^\s*export\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?(?:function\*?|class|interface|type|enum|const|let|var|namespace)\s+(\w+)`)
	tsMem   = regexp.MustCompile(`^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:public|protected)\s+(?:static\s+)?(?:readonly\s+)?(?:abstract\s+)?(?:async\s+)?(?:get\s+|set\s+)?(\w+)`)
	genInner = regexp.MustCompile(`<[^<>]*>`)
	lastWord = regexp.MustCompile(`(\w+)\s*$`)
	gutter   = regexp.MustCompile(`^(\d+)\| ?`)
)

// Symbols scans masked source lines (nums[i] is the original line number of
// lines[i]) and returns every public/protected/internal declaration (C#) or
// exported / public member (TypeScript).
func Symbols(lines []string, nums []int, lang Lang) []Symbol {
	var out []Symbol
	for i, l := range lines {
		var name string
		if lang == CSharp {
			name = csSymbol(l)
		} else {
			name = tsSymbol(l)
		}
		if name != "" {
			out = append(out, Symbol{name, nums[i]})
		}
	}
	return out
}

func csSymbol(l string) string {
	m := csMods.FindStringSubmatch(l)
	if m == nil {
		return ""
	}
	mods := m[1]
	if strings.Contains(mods, "private") || !(strings.Contains(mods, "public") || strings.Contains(mods, "protected") || strings.Contains(mods, "internal")) {
		return ""
	}
	rest := strings.TrimSpace(m[2])
	if t := csType.FindStringSubmatch(rest); t != nil {
		return t[1]
	}
	if d := csDeleg.FindStringSubmatch(rest); d != nil {
		return d[1]
	}
	if i := strings.IndexAny(rest, "({=;"); i >= 0 {
		rest = rest[:i]
	}
	for {
		n := genInner.ReplaceAllString(rest, "")
		if n == rest {
			break
		}
		rest = n
	}
	if w := lastWord.FindStringSubmatch(rest); w != nil {
		return w[1]
	}
	return ""
}

func tsSymbol(l string) string {
	if m := tsExp.FindStringSubmatch(l); m != nil {
		return m[1]
	}
	if m := tsMem.FindStringSubmatch(l); m != nil && !strings.HasSuffix(strings.TrimSpace(l), ",") { // a trailing comma marks a constructor parameter property
		return m[1]
	}
	return ""
}

// SymbolsOfSource scans an original file.
func SymbolsOfSource(src []byte, lang Lang) []Symbol {
	text := strings.ReplaceAll(string(src), "\r\n", "\n")
	lines := strings.Split(string(Mask([]byte(text), lang)), "\n")
	nums := make([]int, len(lines))
	for i := range nums {
		nums[i] = i + 1
	}
	return Symbols(lines, nums, lang)
}

// SymbolsOfView scans a numbered view using only its text and gutter numbers.
func SymbolsOfView(view string, lang Lang) []Symbol {
	var body []string
	var nums []int
	for _, l := range strings.Split(strings.TrimRight(view, "\n"), "\n") {
		g := gutter.FindStringSubmatch(l)
		if g == nil {
			continue
		}
		n, _ := strconv.Atoi(g[1])
		nums = append(nums, n)
		body = append(body, l[len(g[0]):])
	}
	masked := strings.Split(string(Mask([]byte(strings.Join(body, "\n")), lang)), "\n")
	return Symbols(masked, nums, lang)
}

// GutterFaithful reports how many view lines carry a number whose original line
// starts with the same text.
func GutterFaithful(src []byte, view string) (ok, total int) {
	orig := strings.Split(strings.ReplaceAll(string(src), "\r\n", "\n"), "\n")
	for _, l := range strings.Split(strings.TrimRight(view, "\n"), "\n") {
		g := gutter.FindStringSubmatch(l)
		if g == nil {
			continue
		}
		n, _ := strconv.Atoi(g[1])
		body := l[len(g[0]):]
		if i := strings.Index(body, " /*…"); i >= 0 {
			body = body[:i]
		}
		total++
		if n >= 1 && n <= len(orig) && strings.HasPrefix(strings.TrimSpace(orig[n-1]), strings.TrimSpace(body)) {
			ok++
		}
	}
	return
}

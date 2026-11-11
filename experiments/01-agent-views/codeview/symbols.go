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
	csMods   = regexp.MustCompile(`^\s*(?:\[[^\]]*\]\s*)*((?:(?:public|protected|internal|private|static|abstract|sealed|virtual|override|partial|readonly|async|new|unsafe|extern|required|file|const|volatile)\s+)+)(.*)$`)
	csType   = regexp.MustCompile(`^(?:class|struct|interface|enum|record(?:\s+(?:class|struct))?)\s+(\w+)`)
	csDeleg  = regexp.MustCompile(`^delegate\s+[^(]*?(\w+)\s*(?:<[^()]*>)?\s*\(`)
	tsExp    = regexp.MustCompile(`^\s*export\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?(?:const\s+enum|function\*?|class|interface|type|enum|const|let|var|namespace)\s+(\w+)`)
	tsDef    = regexp.MustCompile(`^\s*export\s+default\b`)
	tsList   = regexp.MustCompile(`^\s*export\s+(?:type\s+)?\{(.*)$`)
	tsClass  = regexp.MustCompile(`\bclass(?:\s+[A-Za-z_$][\w$]*|\s*[{<])`)
	csOper   = regexp.MustCompile(`\boperator\s+([^(]+?)\s*\(`)
	csIdx    = regexp.MustCompile(`\bthis\s*\[`)
	csMore   = regexp.MustCompile(`^\s*(\w+)\s*(?:=|$)`)
	tsMem    = regexp.MustCompile(`^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(public|protected|private)\s+)?(?:(?:static|readonly|abstract|override|async|declare|accessor)\s+)*(?:(?:get|set)\s+)?\*?(\w+)\s*[?!]?\s*(?:[(<:=;]|$)`)
	genInner = regexp.MustCompile(`<[^<>]*>`)
	lastWord = regexp.MustCompile(`(\w+)\s*$`)
	gutter   = regexp.MustCompile(`^(\d+)\| ?`)
)

// Symbols scans masked source lines (nums[i] is the original line number of
// lines[i]) and returns every public/protected/internal declaration (C#) or
// exported / public member (TypeScript).
func Symbols(lines []string, nums []int, lang Lang) []Symbol {
	var out []Symbol
	ts := &tsState{}
	for i, l := range lines {
		var names []string
		if lang == CSharp {
			names = csSymbols(l)
		} else {
			names = ts.line(l)
		}
		for _, n := range names {
			out = append(out, Symbol{n, nums[i]})
		}
	}
	return out
}

// splitTop splits s at commas that sit outside any (), [], {} or <>.
func splitTop(s string) []string {
	var parts []string
	depth, start := 0, 0
	for i := 0; i < len(s); i++ {
		switch s[i] {
		case '(', '[', '{', '<':
			depth++
		case ')', ']', '}', '>':
			depth = max(depth-1, 0)
		case ',':
			if depth == 0 {
				parts = append(parts, s[start:i])
				start = i + 1
			}
		}
	}
	return append(parts, s[start:])
}

func csSymbols(l string) []string {
	m := csMods.FindStringSubmatch(l)
	if m == nil {
		return nil
	}
	mods := m[1]
	if strings.Contains(mods, "private") || !(strings.Contains(mods, "public") || strings.Contains(mods, "protected") || strings.Contains(mods, "internal")) {
		return nil
	}
	rest := strings.TrimSpace(m[2])
	if t := csType.FindStringSubmatch(rest); t != nil {
		return []string{t[1]}
	}
	if d := csDeleg.FindStringSubmatch(rest); d != nil {
		return []string{d[1]}
	}
	if o := csOper.FindStringSubmatch(rest); o != nil {
		return []string{"operator " + o[1]}
	}
	if loc := csIdx.FindStringIndex(rest); loc != nil && !strings.ContainsAny(rest[:loc[0]], "(={") {
		return []string{"this"}
	}
	if i := strings.IndexByte(rest, ';'); i >= 0 {
		rest = rest[:i]
	}
	parts := splitTop(rest)
	first := parts[0]
	fieldLike := true
	if i := strings.IndexAny(first, "({=;"); i >= 0 {
		fieldLike = first[i] == '='
		first = first[:i]
	}
	for {
		n := genInner.ReplaceAllString(first, "")
		if n == first {
			break
		}
		first = n
	}
	w := lastWord.FindStringSubmatch(first)
	if w == nil {
		return nil
	}
	names := []string{w[1]}
	if fieldLike {
		for _, p := range parts[1:] {
			if x := csMore.FindStringSubmatch(p); x != nil {
				names = append(names, x[1])
			}
		}
	}
	return names
}

// tsState follows brace nesting across lines so that members of a class body can
// be told from object literals, parameters and function bodies.
type tsState struct {
	stack        []byte // 'c' class body, 'b' any other brace, paren or bracket
	pendingClass bool
	inExport     bool // inside a multi-line `export { ... }` list
	cont         bool // previous line ended mid-expression
}

func (s *tsState) line(l string) []string {
	atClass := len(s.stack) > 0 && s.stack[len(s.stack)-1] == 'c'
	var names []string
	switch {
	case s.inExport:
		names, s.inExport = exportNames(l)
	case tsList.MatchString(l):
		names, s.inExport = exportNames(tsList.FindStringSubmatch(l)[1])
	case tsExp.MatchString(l):
		names = []string{tsExp.FindStringSubmatch(l)[1]}
	case tsDef.MatchString(l):
		names = []string{"default"}
	case atClass && !s.cont:
		if m := tsMem.FindStringSubmatch(l); m != nil && m[1] != "private" && m[2] != "constructor" {
			names = []string{m[2]}
		}
	}
	if tsClass.MatchString(l) {
		s.pendingClass = true
	}
	if t := strings.TrimSpace(l); t != "" {
		s.cont = strings.IndexByte("+-*/&|=?:,(.", t[len(t)-1]) >= 0
	}
	ang := 0
	for i := 0; i < len(l); i++ {
		switch l[i] {
		case '<':
			if s.pendingClass {
				ang++
			}
		case '>':
			if ang > 0 && (i == 0 || l[i-1] != '=') {
				ang--
			}
		case '{':
			k := byte('b')
			if s.pendingClass && ang == 0 {
				// only top-level classes are public API; a class inside a function body is local
				if len(s.stack) == 0 {
					k = 'c'
				}
				s.pendingClass = false
			}
			s.stack = append(s.stack, k)
		case '(', '[':
			s.stack = append(s.stack, 'b')
		case '}', ')', ']':
			if len(s.stack) > 0 {
				s.stack = s.stack[:len(s.stack)-1]
			}
		}
	}
	return names
}

// exportNames reads the names in `a, b as c, type D` up to a closing '}'. It
// reports whether the list is still open at the end of the text.
func exportNames(text string) ([]string, bool) {
	open := true
	if i := strings.IndexByte(text, '}'); i >= 0 {
		text, open = text[:i], false
	}
	var out []string
	for _, p := range strings.Split(text, ",") {
		f := strings.Fields(p)
		if len(f) > 0 && f[0] == "type" && len(f) > 1 {
			f = f[1:]
		}
		if len(f) == 0 {
			continue
		}
		out = append(out, f[len(f)-1])
	}
	return out, open
}

// SymbolsOfSource scans an original file.
func SymbolsOfSource(src []byte, lang Lang) []Symbol {
	text := normalize(src)
	lines := strings.Split(string(Mask([]byte(text), lang)), "\n")
	nums := make([]int, len(lines))
	for i := range nums {
		nums[i] = i + 1
	}
	return Symbols(lines, nums, lang)
}

// viewBody splits a numbered view into gutter numbers and line text.
func viewBody(view string) (nums []int, body []string) {
	for _, l := range strings.Split(strings.TrimRight(view, "\n"), "\n") {
		g := gutter.FindStringSubmatch(l)
		if g == nil {
			continue
		}
		n, _ := strconv.Atoi(g[1])
		nums = append(nums, n)
		body = append(body, l[len(g[0]):])
	}
	return
}

// SymbolsOfView scans a numbered view using only its text and gutter numbers.
func SymbolsOfView(view string, lang Lang) []Symbol {
	nums, body := viewBody(view)
	masked := strings.Split(string(Mask([]byte(strings.Join(body, "\n")), lang)), "\n")
	return Symbols(masked, nums, lang)
}

var markerRe = regexp.MustCompile(` /\*…\d+-\d+\*/ `)

// SignatureBreaks counts elision markers in a numbered view that sit where a
// signature or an import/export list should have been kept whole: inside open
// parens after one of ( , : | & < =, or in a brace opened by an import or export
// line. A non-zero count means the cut removed something the README promises to keep.
func SignatureBreaks(view string, lang Lang) int {
	_, body := viewBody(view)
	text := strings.Join(body, "\n")
	masked := Mask([]byte(text), lang)
	n := 0
	for _, loc := range markerRe.FindAllStringIndex(text, -1) {
		brace := strings.LastIndexByte(text[:loc[0]], '{')
		if brace < 0 {
			continue
		}
		head := strings.TrimSpace(string(masked[strings.LastIndexByte(text[:brace], '\n')+1 : brace]))
		// innermost open bracket before the brace: object-literal values inside a call
		// (`defineConfig({ a: {`) sit in a '{', a parameter type (`({ a }: {`) sits in the '('.
		var open []int
		for i, c := range masked[:brace] {
			switch c {
			case '(', '{', '[':
				open = append(open, i)
			case ')', '}', ']':
				if len(open) > 0 {
					open = open[:len(open)-1]
				}
			}
		}
		inParens := len(open) > 0 && masked[open[len(open)-1]] == '(' && declParen(masked, open[len(open)-1])
		before := strings.TrimSpace(string(masked[:brace]))
		if listHeadRe.MatchString(head) ||
			inParens && before != "" && strings.IndexByte("(,:|&<=", before[len(before)-1]) >= 0 {
			n++
		}
	}
	return n
}

// GutterFaithful reports how many view lines carry a number whose original line
// starts with the same text.
func GutterFaithful(src []byte, view string) (ok, total int) {
	orig := strings.Split(normalize(src), "\n")
	nums, body := viewBody(view)
	for k, n := range nums {
		b := body[k]
		if i := strings.Index(b, " /*…"); i >= 0 {
			b = b[:i]
		}
		total++
		if n >= 1 && n <= len(orig) && strings.HasPrefix(strings.TrimSpace(orig[n-1]), strings.TrimSpace(b)) {
			ok++
		}
	}
	return
}

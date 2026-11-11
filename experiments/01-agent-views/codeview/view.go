package main

import (
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// Options controls the rendered view.
type Options struct {
	Numbers bool // prefix every line with its original line number ("12| ")
}

type span struct{ from, to int } // body bytes between '{' and its '}'

var (
	typeKw     = regexp.MustCompile(`\b(class|struct|interface|enum|record|namespace|module)\b`)
	typeOnlyRe = regexp.MustCompile(`\b(interface|enum)\b|\btype\s+\w+\s*(<[^=]*>)?\s*=|\bdeclare\s+global\b`)
)

// matchBraces pairs every '{' with its '}' in the masked text.
func matchBraces(m []byte) (map[int]int, error) {
	match := map[int]int{}
	var stack []int
	for i, c := range m {
		switch c {
		case '{':
			stack = append(stack, i)
		case '}':
			if len(stack) == 0 {
				return nil, errors.New("unbalanced '}'")
			}
			match[stack[len(stack)-1]] = i
			stack = stack[:len(stack)-1]
		}
	}
	if len(stack) != 0 {
		return nil, errors.New("unbalanced '{'")
	}
	return match, nil
}

const (
	kindBody = iota
	kindType
	kindTypeOnly
)

func classify(header string) int {
	if typeOnlyRe.MatchString(header) {
		return kindTypeOnly
	}
	loc := typeKw.FindStringIndex(header)
	if loc == nil {
		return kindBody
	}
	paren := strings.IndexByte(header, '(')
	kw := header[loc[0]:loc[1]]
	if paren < 0 || loc[0] < paren || kw == "record" {
		return kindType
	}
	return kindBody
}

func elisions(m []byte, match map[int]int) []span {
	var out []span
	var walk func(a, b int, all bool)
	walk = func(a, b int, all bool) {
		boundary := a
		for i := a; i < b; i++ {
			switch m[i] {
			case ';', '}':
				boundary = i + 1
			case '{':
				cl := match[i]
				kind := classify(stripAttrs(string(m[boundary:i])))
				switch {
				case all || kind != kindBody:
					walk(i+1, cl, all || kind == kindTypeOnly)
				case cl-i > 100 || strings.IndexByte(string(m[i+1:cl]), '\n') >= 0:
					out = append(out, span{i + 1, cl})
				}
				i = cl
				boundary = cl + 1
			}
		}
	}
	walk(0, len(m), false)
	return out
}

// View renders the cut-down view of src: declarations, types, doc comments and
// import lines stay; multi-line bodies become `{ /*…from-to*/ }` with the original
// line range. Blank lines are dropped. On unbalanced braces (a lexer miss) it
// returns an error so the caller can fall back to the full file.
func View(src []byte, lang Lang, opt Options) (string, error) {
	text := strings.ReplaceAll(string(src), "\r\n", "\n")
	b := []byte(text)
	m := Mask(b, lang)
	match, err := matchBraces(m)
	if err != nil {
		return "", err
	}
	els := elisions(m, match)
	sort.Slice(els, func(i, j int) bool { return els[i].from < els[j].from })

	var sb strings.Builder
	line := 1
	lineStart := true
	var cur strings.Builder
	curNo := 1
	flush := func() {
		s := strings.TrimRight(cur.String(), " \t")
		cur.Reset()
		if strings.TrimSpace(s) == "" {
			return
		}
		if opt.Numbers {
			fmt.Fprintf(&sb, "%d| ", curNo)
		}
		sb.WriteString(s)
		sb.WriteByte('\n')
	}
	ei := 0
	for i := 0; i < len(b); {
		if lineStart {
			curNo = line
			lineStart = false
		}
		if ei < len(els) && i == els[ei].from {
			e := els[ei]
			endLine := line + strings.Count(text[e.from:e.to], "\n")
			fmt.Fprintf(&cur, " /*…%d-%d*/ ", line, endLine)
			line = endLine
			i = e.to
			ei++
			continue
		}
		if b[i] == '\n' {
			flush()
			line++
			lineStart = true
			i++
			continue
		}
		cur.WriteByte(b[i])
		i++
	}
	flush()
	return sb.String(), nil
}

var attrRe = regexp.MustCompile(`\[[^\[\]]*\]`)

func stripAttrs(h string) string {
	for {
		n := attrRe.ReplaceAllString(h, " ")
		if n == h {
			return h
		}
		h = n
	}
}

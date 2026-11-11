package main

// Lang selects the lexical rules used to find comments and strings.
type Lang int

const (
	CSharp Lang = iota
	TypeScript
)

// LangOf maps a file name to a language, or false when unsupported.
func LangOf(name string) (Lang, bool) {
	n := len(name)
	switch {
	case n > 3 && name[n-3:] == ".cs":
		return CSharp, true
	case n > 5 && name[n-5:] == ".d.ts":
		return TypeScript, false
	case n > 3 && name[n-3:] == ".ts", n > 4 && name[n-4:] == ".tsx":
		return TypeScript, true
	}
	return TypeScript, false
}

type scanner struct {
	src  []byte
	out  []byte
	lang Lang
}

// Mask returns src with comments and string/char/regex literals blanked to spaces.
// Newlines and length are preserved, so offsets and line numbers still match src.
func Mask(src []byte, lang Lang) []byte {
	s := &scanner{src: src, out: append([]byte(nil), src...), lang: lang}
	s.code(0, false)
	return s.out
}

func (s *scanner) blank(i, j int) {
	if j > len(s.out) {
		j = len(s.out)
	}
	for k := i; k < j; k++ {
		if s.out[k] != '\n' {
			s.out[k] = ' '
		}
	}
}

func (s *scanner) at(i int) byte {
	if i < len(s.src) {
		return s.src[i]
	}
	return 0
}

// code scans code from i. With inHole it stops at the unmatched '}' that closes
// an interpolation hole and returns its index.
func (s *scanner) code(i int, inHole bool) int {
	depth := 0
	var lastSig byte // last significant (non-space) byte, for regex detection
	lastWord := ""
	for i < len(s.src) {
		c := s.src[i]
		switch {
		case c == '/' && s.at(i+1) == '/':
			j := i
			for j < len(s.src) && s.src[j] != '\n' {
				j++
			}
			s.blank(i, j)
			i = j
			continue
		case c == '/' && s.at(i+1) == '*':
			j := i + 2
			for j < len(s.src) && !(s.src[j] == '*' && s.at(j+1) == '/') {
				j++
			}
			j += 2
			s.blank(i, j)
			i = j
			continue
		case c == '{':
			depth++
		case c == '}':
			if inHole && depth == 0 {
				return i
			}
			depth--
		case c == '"' || c == '\'' || c == '`' || c == '$' || c == '@':
			if j, ok := s.str(i); ok {
				s.blank(i, j)
				i = j
				lastSig = '"'
				lastWord = ""
				continue
			}
		case c == '/' && s.lang == TypeScript && regexAllowed(lastSig, lastWord) && s.at(i+1) != '>':
			if j, ok := s.regex(i); ok {
				s.blank(i, j)
				i = j
				lastSig = '"'
				lastWord = ""
				continue
			}
		}
		if c == ' ' || c == '\t' || c == '\n' || c == '\r' {
			i++
			continue
		}
		if isIdent(c) {
			j := i
			for j < len(s.src) && isIdent(s.src[j]) {
				j++
			}
			lastWord = string(s.src[i:j])
			lastSig = 'a'
			i = j
			continue
		}
		lastSig = c
		lastWord = ""
		i++
	}
	return len(s.src)
}

func isIdent(c byte) bool {
	return c == '_' || c == '$' || c >= '0' && c <= '9' || c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= 0x80
}

func regexAllowed(last byte, word string) bool {
	switch word {
	case "return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else":
		return true
	}
	if last == 0 {
		return true
	}
	switch last {
	case '(', ',', '=', ':', '[', '!', '&', '|', '?', '{', ';', '+', '-', '*', '%', '~', '^':
		return true
	}
	return false
}

func (s *scanner) regex(i int) (int, bool) {
	j := i + 1
	inClass := false
	for j < len(s.src) && s.src[j] != '\n' {
		switch s.src[j] {
		case '\\':
			j++
		case '[':
			inClass = true
		case ']':
			inClass = false
		case '/':
			if !inClass {
				j++
				for j < len(s.src) && (s.src[j] >= 'a' && s.src[j] <= 'z') {
					j++
				}
				return j, true
			}
		}
		j++
	}
	return 0, false
}

// str recognises a string-like literal starting at i and returns the index just past it.
func (s *scanner) str(i int) (int, bool) {
	c := s.src[i]
	if s.lang == TypeScript {
		switch c {
		case '\'', '"':
			j := s.quoted(i+1, c)
			return j, j > 0
		case '`':
			return s.template(i + 1), true
		}
		return 0, false
	}
	// C#
	j := i
	verbatim, interp := false, false
	for j < len(s.src) && (s.src[j] == '$' || s.src[j] == '@') {
		if s.src[j] == '@' {
			verbatim = true
		} else {
			interp = true
		}
		j++
	}
	if j-i > 3 {
		return 0, false
	}
	switch s.at(j) {
	case '"':
		n := 0
		for s.at(j+n) == '"' {
			n++
		}
		if n >= 3 { // raw string literal
			k := j + n
			for k < len(s.src) {
				m := 0
				for s.at(k+m) == '"' {
					m++
				}
				if m >= n {
					return k + n, true
				}
				k += max(m, 1)
			}
			return len(s.src), true
		}
		if verbatim {
			return s.verbatim(j+1, interp), true
		}
		return s.quotedCS(j+1, interp), true
	case '\'':
		if j != i {
			return 0, false
		}
		if s.at(j+1) == '\\' {
			k := j + 2
			for k < len(s.src) && s.src[k] != '\'' && s.src[k] != '\n' {
				k++
			}
			return k + 1, true
		}
		if s.at(j+2) == '\'' {
			return j + 3, true
		}
	}
	return 0, false
}

func (s *scanner) quoted(j int, q byte) int {
	for j < len(s.src) && s.src[j] != '\n' {
		if s.src[j] == '\\' {
			j += 2
			continue
		}
		if s.src[j] == q {
			return j + 1
		}
		j++
	}
	return 0 // unterminated on its line: JSX text, not a string
}

func (s *scanner) quotedCS(j int, interp bool) int {
	for j < len(s.src) && s.src[j] != '\n' {
		switch {
		case s.src[j] == '\\':
			j += 2
			continue
		case s.src[j] == '"':
			return j + 1
		case interp && s.src[j] == '{':
			if s.at(j+1) == '{' {
				j += 2
				continue
			}
			j = s.code(j+1, true) + 1
			continue
		}
		j++
	}
	return j
}

func (s *scanner) verbatim(j int, interp bool) int {
	for j < len(s.src) {
		switch {
		case s.src[j] == '"':
			if s.at(j+1) == '"' {
				j += 2
				continue
			}
			return j + 1
		case interp && s.src[j] == '{':
			if s.at(j+1) == '{' {
				j += 2
				continue
			}
			j = s.code(j+1, true) + 1
			continue
		}
		j++
	}
	return j
}

func (s *scanner) template(j int) int {
	for j < len(s.src) {
		switch {
		case s.src[j] == '\\':
			j += 2
			continue
		case s.src[j] == '`':
			return j + 1
		case s.src[j] == '$' && s.at(j+1) == '{':
			j = s.code(j+2, true) + 1
			continue
		}
		j++
	}
	return j
}

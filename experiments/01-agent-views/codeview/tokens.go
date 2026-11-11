package main

import "unicode"

// TokensBytes4 is the crude bytes/4 estimate.
func TokensBytes4(s string) int { return (len(s) + 3) / 4 }

// TokensPieces estimates BPE tokens offline: split into identifier words (at case
// changes), digit runs, punctuation runs and whitespace runs, then charge each
// piece by length. It is a proxy for relative cost, not Claude's tokenizer.
func TokensPieces(s string) int {
	rs := []rune(s)
	n := 0
	ceil := func(a, b int) int { return (a + b - 1) / b }
	for i := 0; i < len(rs); {
		r := rs[i]
		switch {
		case unicode.IsLetter(r):
			j := i + 1
			for j < len(rs) && unicode.IsLetter(rs[j]) && !(unicode.IsUpper(rs[j]) && unicode.IsLower(rs[j-1])) {
				j++
			}
			n += ceil(j-i, 6)
			i = j
		case unicode.IsDigit(r):
			j := i + 1
			for j < len(rs) && unicode.IsDigit(rs[j]) {
				j++
			}
			n += ceil(j-i, 3)
			i = j
		case unicode.IsSpace(r):
			j := i + 1
			for j < len(rs) && unicode.IsSpace(rs[j]) {
				j++
			}
			n++
			i = j
		default:
			j := i + 1
			for j < len(rs) && !unicode.IsLetter(rs[j]) && !unicode.IsDigit(rs[j]) && !unicode.IsSpace(rs[j]) {
				j++
			}
			n += ceil(j-i, 2)
			i = j
		}
	}
	return n
}

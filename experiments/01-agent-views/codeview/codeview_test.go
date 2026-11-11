package main

import (
	"strings"
	"testing"
)

const csSample = `using System;

namespace Demo;

/// <summary>A thing.</summary>
[Serializable]
public sealed class Thing : IThing
{
    private int _x;
    public string Name { get; set; } = "a { brace";

    /// <summary>Adds.</summary>
    public int Add(int a, int b)
    {
        var s = $"{a} + {b}: {{literal}} {(a > b ? "big" : "small")}";
        // } stray brace in comment
        return a + b;
    }

    public int Twice(int a) => a * 2;

    internal enum Kind { A, B }

    protected virtual Task<List<int>> RunAsync<T>(T arg)
    {
        return Task.FromResult(new List<int> { 1, 2 });
    }
}

public interface IThing
{
    int Add(int a, int b);
}

public record Pair(int A, int B)
{
    public int Sum()
    {
        return A + B;
    }
}
`

func mustView(t *testing.T, src string, lang Lang, numbers bool) string {
	t.Helper()
	v, err := View([]byte(src), lang, Options{Numbers: numbers})
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestCSharpElidesBodiesKeepsSignatures(t *testing.T) {
	v := mustView(t, csSample, CSharp, true)
	for _, want := range []string{
		"public sealed class Thing : IThing",
		"/// <summary>Adds.</summary>",
		"public int Add(int a, int b)",
		"{ /*…14-18*/ }", // body of Add, original lines 14 to 19
		"public int Twice(int a) => a * 2;",
		"internal enum Kind { A, B }",
		"protected virtual Task<List<int>> RunAsync<T>(T arg)",
		"public record Pair(int A, int B)",
		"public int Sum()",
		"int Add(int a, int b);",
	} {
		if !strings.Contains(v, want) {
			t.Errorf("view lacks %q\n%s", want, v)
		}
	}
	for _, bad := range []string{"Task.FromResult", "stray brace", "return a + b", "literal"} {
		if strings.Contains(v, bad) {
			t.Errorf("view still has %q\n%s", bad, v)
		}
	}
}

func TestMarkerRangeMatchesOriginalLines(t *testing.T) {
	v := mustView(t, csSample, CSharp, true)
	lines := strings.Split(csSample, "\n")
	if strings.TrimSpace(lines[13]) != "{" || strings.TrimSpace(lines[17]) != "}" {
		t.Fatal("sample moved; fix the expected range")
	}
	if !strings.Contains(v, "14|     { /*…14-18*/ }") {
		t.Errorf("marker line wrong\n%s", v)
	}
}

func TestSymbolsSurviveTheCut(t *testing.T) {
	for _, tc := range []struct {
		src  string
		lang Lang
		min  int
	}{{csSample, CSharp, 9}, {tsSample, TypeScript, 7}} {
		v := mustView(t, tc.src, tc.lang, true)
		orig := SymbolsOfSource([]byte(tc.src), tc.lang)
		got := SymbolsOfView(v, tc.lang)
		if len(orig) < tc.min {
			t.Fatalf("oracle found only %d symbols: %v", len(orig), orig)
		}
		if len(got) != len(orig) {
			t.Fatalf("orig %v\nview %v", orig, got)
		}
		for i := range orig {
			if orig[i] != got[i] {
				t.Errorf("symbol %v became %v", orig[i], got[i])
			}
		}
		if ok, total := GutterFaithful([]byte(tc.src), v); ok != total {
			t.Errorf("gutter faithful %d/%d\n%s", ok, total, v)
		}
	}
}

func TestCSharpSymbolNames(t *testing.T) {
	names := map[string]string{}
	for _, s := range SymbolsOfSource([]byte(csSample), CSharp) {
		names[s.Name] = "x"
	}
	for _, n := range []string{"Thing", "Name", "Add", "Twice", "Kind", "RunAsync", "IThing", "Pair", "Sum"} {
		if _, ok := names[n]; !ok {
			t.Errorf("missing symbol %s in %v", n, names)
		}
	}
	if _, ok := names["_x"]; ok {
		t.Error("private field counted as public")
	}
}

const tsSample = "import { a } from './a';\n" +
	"/** Doc line. */\n" +
	"export interface Opts { nested: { deep: number }; name: string }\n" +
	"export type Shape = {\n  w: number;\n  h: number;\n};\n" +
	"export enum Mode {\n  A = 'a',\n  B = `b${1}`,\n}\n" +
	"export const re = /[/}]+/g;\n" +
	"export function area(s: Shape): number {\n  const t = `${s.w}{${s.h}`;\n  return s.w * s.h; // }\n}\n" +
	"export class Box<T> extends Base {\n" +
	"  public label = 'x';\n" +
	"  private secret = 1;\n" +
	"  constructor(\n    public readonly id: string,\n  ) {\n    super();\n  }\n" +
	"  public async load(): Promise<T> {\n    const o = { a: 1 };\n    return this.fetch(o);\n  }\n" +
	"}\n" +
	"export default function Page() {\n  return (\n    <p>It's {x} </p>\n  );\n}\n"

func TestTypeScriptViewKeepsTypesElidesBodies(t *testing.T) {
	v := mustView(t, tsSample, TypeScript, false)
	for _, want := range []string{
		"export interface Opts { nested: { deep: number }; name: string }",
		"w: number;", "h: number;", "A = 'a',",
		"export function area(s: Shape): number",
		"export class Box<T> extends Base",
		"public async load(): Promise<T>",
		"export default function Page()",
	} {
		if !strings.Contains(v, want) {
			t.Errorf("view lacks %q\n%s", want, v)
		}
	}
	for _, bad := range []string{"s.w * s.h", "this.fetch", "super()", "return ("} {
		if strings.Contains(v, bad) {
			t.Errorf("view still has %q\n%s", bad, v)
		}
	}
	if strings.Contains(v, "1| ") {
		t.Error("numbers off but gutter present")
	}
}

func TestTypeScriptSymbols(t *testing.T) {
	got := map[string]bool{}
	for _, s := range SymbolsOfSource([]byte(tsSample), TypeScript) {
		got[s.Name] = true
	}
	for _, n := range []string{"Opts", "Shape", "Mode", "re", "area", "Box", "label", "load", "Page"} {
		if !got[n] {
			t.Errorf("missing %s in %v", n, got)
		}
	}
	if got["secret"] || got["id"] {
		t.Errorf("non-public member or ctor parameter counted: %v", got)
	}
}

func TestJSXApostropheDoesNotBreakBraces(t *testing.T) {
	src := "export function A() {\n  return <p>don't {x}</p>;\n}\n"
	if _, err := View([]byte(src), TypeScript, Options{}); err != nil {
		t.Fatal(err)
	}
}

func TestUnbalancedFallsBack(t *testing.T) {
	if _, err := View([]byte("class A {\n"), CSharp, Options{}); err == nil {
		t.Fatal("expected error")
	}
}

func TestVerbatimAndRawStrings(t *testing.T) {
	src := "class A\n{\n    string s = @\"a \"\"}\"\" b\";\n    string r = \"\"\"\n      } { \"x\"\n      \"\"\";\n    void M()\n    {\n        var c = '{';\n        var d = '\\'';\n    }\n}\n"
	v := mustView(t, src, CSharp, false)
	if strings.Contains(v, "var c") || !strings.Contains(v, "void M()") {
		t.Errorf("bad view\n%s", v)
	}
}

func TestCRLFAndBlankLines(t *testing.T) {
	v := mustView(t, "class A\r\n{\r\n\r\n    void M()\r\n    {\r\n        x();\r\n    }\r\n}\r\n", CSharp, false)
	if strings.Contains(v, "\r") || strings.Contains(v, "\n\n") {
		t.Errorf("%q", v)
	}
}

func TestTokenProxiesShrinkWithTheView(t *testing.T) {
	v := mustView(t, csSample, CSharp, true)
	if TokensPieces(v) >= TokensPieces(csSample) || TokensBytes4(v) >= TokensBytes4(csSample) {
		t.Error("view not smaller")
	}
	if TokensPieces("fooBarBaz  = 12345;") < 5 {
		t.Error("pieces too low")
	}
}

func TestLangOf(t *testing.T) {
	for name, want := range map[string]bool{"a.cs": true, "a.ts": true, "a.tsx": true, "a.d.ts": false, "a.go": false} {
		if _, ok := LangOf(name); ok != want {
			t.Errorf("%s: %v", name, ok)
		}
	}
}

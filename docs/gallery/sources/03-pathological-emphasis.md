# Pathological emphasis

CommonMark's emphasis algorithm (§6.2) has subtle rules: left-flanking, right-flanking, the rule of 3, intraword underscores, and the interaction between `*` and `_`. These cases are where most lightweight markdown parsers diverge from each other.

## The rule of 3

`**foo** bar**baz** quux` should make the first pair emphasise `foo` and the second pair emphasise `baz`, with `bar` between them as plain text.

**foo** bar**baz** quux

## Triple asterisk

`***foo***` should render as nested italic-inside-bold.

***foo***

Triple in mid-sentence: This is ***strong and italic*** at once.

## Triple with mismatched closing

`***foo** bar*` — opens with three, closes with two-then-one. The bold should close at `**`, the italic at the final `*`.

***foo** bar*

`*foo **bar***` — opens with one then two, closes with three. Italic closes at the last `*`, bold at the middle pair.

*foo **bar***

## Adjacent emphasis runs

`**bold1****bold2**` — two adjacent bold runs with no space.

**bold1****bold2**

`*italic1**italic2*` — italic opens, italic continues, double asterisk in middle should not become bold.

*italic1**italic2*

## Intraword

`snake_case` and `my_python_var` — underscores intraword should stay literal.

These names are common: snake_case, _leading_underscore, trailing_underscore_, double__internal.

`a*b*c` — asterisks intraword DO emphasise, by CommonMark spec.

The word a*b*c has an emphasis in the middle.

## Emphasis around punctuation

`foo*bar*baz` — emphasis at word boundary inside.

foo*bar*baz

`*$5*` — currency symbol; should NOT emphasise (punctuation flanking rule).

The price is *$5* today.

`*€5*`, `*£5*`, `*¥5*` — currency symbols across regions.

Prices in *€5*, *£5*, *¥5* form should stay literal.

## Emphasis spanning a newline

This *italic continues
on the next line* and closes.

And **bold spans
across a line** in the same way.

## Pathological depth

*a *b *c *d *e *f *g *h *i *j* i* h* g* f* e* d* c* b* a* — ten levels of opening, ten levels of closing.

## Unmatched

*unclosed italic should be literal asterisk and the rest of the line is fine.

**unclosed bold same story; literal asterisks.

`unclosed code span — backtick should be literal too.

## Empty

`****` — four asterisks, no content. Should be either four literal asterisks, or empty emphasis (browser does the former, spec says the former).

The bareword ****  has four asterisks.

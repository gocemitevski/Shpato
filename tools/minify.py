#!/usr/bin/env python3
"""Minify the hand-written assets into assets/*.min.{css,js}.

The catalogue has no toolchain and is not getting one: this is Python 3
standard library, it reads the sources and writes a sibling file, and it is
deterministic (same input, same bytes, so `git diff --exit-code` stays silent).

What it does — and, more usefully, what it refuses to do:

  * comments go, whether they are /* CSS */ or // JS;
  * runs of spaces and tabs inside a line collapse to one space, and runs of
    blank lines to one newline;
  * spaces next to punctuation (`{ } [ ] ( ) , ; :`) are dropped, since no
    JavaScript or CSS parses them differently;
  * newlines are otherwise KEPT. Automatic semicolon insertion is a footgun and
    a real JS minifier needs a parser and a scope analysis to rename anything;
    this one does not touch identifiers, and it does not join lines. Brotli has
    already compressed what is left, so the remaining win is small and the risk
    of mangling `return\n x` is not worth it.

Tested against the real files: run the app from the minified assets and diff the
rendered DOM against the unminified ones (see the harness), not just `node
--check`, because a minifier that produces valid-but-different code is the
failure mode that matters.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# source -> destination
TARGETS = [
    ("assets/styles.css", "assets/styles.min.css"),
    ("assets/i18n.js", "assets/i18n.min.js"),
    ("assets/app.js", "assets/app.min.js"),
]


def minify_css(src):
    out = []
    i, n = 0, len(src)
    depth = 0          # ( ) — inside these, whitespace can be load-bearing
    quote = ""
    pending = False
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if quote:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "\"'":
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "*":
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                i += 1
            i += 2
            pending = True
            continue
        if c in " \t\r\n\f":
            pending = True
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if pending and out:
            prev = out[-1]
            # Only squeeze at the top level. Inside a value's parentheses a
            # space can be the difference between valid and dropped CSS:
            # `color-mix(in srgb, …)`, `linear-gradient(to right, …)`,
            # `calc(1rem + var(…))` and `rect(0 0 0 0)` all need theirs, and
            # `calc` needs one around `+` and `-`. A collapsed run of one space
            # costs a byte brotli largely hides; mangling a value costs the
            # rule, silently.
            tight = depth == 0 and (c in "{},;:" or prev in "{},;:(" or (prev == ")" and c in "{;}"))
            if not tight and prev not in " \n":
                out.append(" ")
        elif pending and not out:
            pass
        pending = False
        out.append(c)
        i += 1
    s = "".join(out)
    s = re.sub(r";+}", "}", s)                    # a declaration's last ; is noise
    s = re.sub(r"[\n\r]+", "\n", s)
    return s.strip()


KEYWORDS_BEFORE_REGEX = (
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "case", "do", "else", "yield", "await", "throw",
)


def minify_js(src):
    out = []
    i, n = 0, len(src)
    pending = False
    last_token = ""     # for the division-vs-regex decision
    quote = ""

    def prev_char():
        for ch in reversed(out):
            if ch not in " \n":
                return ch
        return ""

    def regex_allowed():
        p = prev_char()
        if p == "" or p in "=(,:[!&|?{};+-*%<>~^":
            return True
        if p.isalnum() or p in "._$)]":
            return last_token in KEYWORDS_BEFORE_REGEX
        return False

    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if quote:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "\"'`":
            quote = c
            out.append(c)
            last_token = ""
            i += 1
            continue
        if c == "/" and nxt == "/":
            i += 2
            while i < n and src[i] not in "\r\n":
                i += 1
            pending = True
            continue
        if c == "/" and nxt == "*":
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                i += 1
            i += 2
            pending = True
            continue
        if c == "/" and regex_allowed():
            out.append(c)
            i += 1
            in_class = False
            while i < n:
                ch = src[i]
                out.append(ch)
                if ch == "\\" and i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    i += 1
                    break
                elif ch == "\n":
                    break
                i += 1
            while i < n and src[i].isalpha():     # flags
                out.append(src[i])
                i += 1
            last_token = ""
            continue
        if c in " \t\f\v":
            pending = True
            i += 1
            continue
        if c in "\r\n":
            # Collapse runs of newlines, and drop a newline that only follows
            # punctuation where joining cannot change the parse.
            j = i
            while j < n and src[j] in "\r\n \t":
                j += 1
            nxt_c = src[j] if j < n else ""
            p = prev_char()
            joinable = p in ";{}," and nxt_c not in "(/+-[" and nxt_c != ""
            if joinable:
                pending = True
                i = j
                continue
            while out and out[-1] in " \t":
                out.pop()
            if out and out[-1] != "\n":
                out.append("\n")
            i = j
            pending = False
            continue
        if pending and out:
            prev = out[-1]
            tight = c in ")}],;:" or prev in "([{"
            if not tight and prev not in " \n":
                out.append(" ")
        pending = False
        out.append(c)
        if c.isalnum() or c in "_$":
            if not last_token.isalnum() and last_token not in ("", "_$"):
                last_token = c
            else:
                last_token += c
        else:
            last_token = ""
        i += 1
    s = "".join(out)
    s = re.sub(r"\n{2,}", "\n", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return s.strip() + "\n"


def minify(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        src = fh.read()
    return minify_css(src) if path.endswith(".css") else minify_js(src)


def main(argv):
    check = "--check" in argv
    status = 0
    for src, dst in TARGETS:
        out = minify(src)
        full = os.path.join(ROOT, dst)
        if check:
            have = open(full, encoding="utf-8").read() if os.path.exists(full) else None
            if have != out:
                sys.stderr.write("stale: %s\n" % dst)
                status = 1
            continue
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
        before = os.path.getsize(os.path.join(ROOT, src))
        after = len(out.encode("utf-8"))
        print("%-20s %7d -> %6d bytes  (%d%%)" % (dst, before, after, 100 * after // before))
    if check and status == 0:
        print("minified assets up to date")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Tiny s-expression reader and writer for KiCad files."""
import re

_TOKEN = re.compile(r'\s*(?:(\()|(\))|("(?:[^"\\]|\\.)*")|([^\s()"]+))', re.S)


class Sym(str):
    """An unquoted atom."""


def parse(text):
    stack = [[]]
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"bad token at {pos}: {text[pos:pos + 40]!r}")
        pos = m.end()
        lp, rp, qs, atom = m.groups()
        if lp:
            stack.append([])
        elif rp:
            top = stack.pop()
            stack[-1].append(top)
        elif qs is not None:
            s = qs[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
            stack[-1].append(s)
        elif atom is not None:
            stack[-1].append(Sym(atom))
    return stack[0]


def _q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def dump(node, indent=0):
    if isinstance(node, list):
        if not node:
            return "()"
        simple = all(not isinstance(x, list) for x in node)
        head = node[0]
        if simple:
            return "(" + " ".join(dump(x) for x in node) + ")"
        out = "(" + dump(head)
        for x in node[1:]:
            if isinstance(x, list):
                out += "\n" + "\t" * (indent + 1) + dump(x, indent + 1)
            else:
                out += " " + dump(x)
        return out + "\n" + "\t" * indent + ")"
    if isinstance(node, Sym):
        return str(node)
    if isinstance(node, bool):
        return "yes" if node else "no"
    if isinstance(node, (int, float)):
        v = round(float(node), 4)
        return str(int(v)) if v == int(v) else repr(v)
    return _q(str(node))


def find(node, head):
    """First child list whose first atom is head."""
    for x in node:
        if isinstance(x, list) and x and x[0] == head:
            return x
    return None


def find_all(node, head):
    return [x for x in node if isinstance(x, list) and x and x[0] == head]

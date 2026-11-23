"""Minimal S-expression parser/printer for KiCad files."""
import re


class Sym(str):
    """Unquoted atom."""


_tok = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def _unescape(s):
    return re.sub(r'\\(.)', r'\1', s)


def parse(text):
    pos = 0
    stack = [[]]
    while True:
        m = _tok.match(text, pos)
        if not m:
            break
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            done = stack.pop()
            stack[-1].append(done)
        elif m.group(3) is not None:
            stack[-1].append(_unescape(m.group(3)))
        else:
            stack[-1].append(Sym(m.group(4)))
    return stack[0]


def q(s):
    s = str(s)
    s = s.replace(chr(92), chr(92) * 2).replace('"', chr(92) + '"')
    return '"' + s + '"'


def fmt(v):
    v = round(float(v), 4)
    s = ('%.4f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def dump(x, ind=0):
    if isinstance(x, list):
        if not x:
            return '()'
        if all(not isinstance(e, list) for e in x):
            return '(' + ' '.join(dump(e) for e in x) + ')'
        head = [dump(e) for e in x if not isinstance(e, list)]
        out = '(' + ' '.join(head)
        for e in x:
            if isinstance(e, list):
                out += '\n' + '\t' * (ind + 1) + dump(e, ind + 1)
        return out + '\n' + '\t' * ind + ')'
    if isinstance(x, Sym):
        return str(x)
    if isinstance(x, bool):
        return 'yes' if x else 'no'
    if isinstance(x, (int, float)):
        return fmt(x)
    return q(x)


def find(node, key):
    return [e for e in node if isinstance(e, list) and e and e[0] == key]


def first(node, key):
    r = find(node, key)
    return r[0] if r else None

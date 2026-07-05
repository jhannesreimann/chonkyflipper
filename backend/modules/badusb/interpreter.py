#!/usr/bin/env python3
"""
DuckyScript interpreter.

Implements a DuckyScript 3.0-flavoured dialect on top of the semantic backend
interface (see backends.py). This is NOT the proprietary Hak5 compiler - it is
an independent interpreter for a compatible subset:

  Keystrokes : STRING, STRINGLN, named keys (ENTER, F5, ...), modifier combos
               (GUI r, CTRL ALT DELETE, ALT F4), REPEAT
  Timing     : DELAY, DEFAULT_DELAY, DEFAULT_CHAR_DELAY/STRINGDELAY, JITTER
  Layout     : LAYOUT <name>
  Comments   : REM, REM_BLOCK ... END_REM
  Variables  : VAR $x = <expr>, then  $x = <expr>
  Control    : IF (<expr>) THEN ... [ELSE IF (<expr>) THEN ...] [ELSE ...] END_IF
               WHILE (<expr>) ... END_WHILE

Expressions support integers (decimal + 0x hex), TRUE/FALSE, variables ($x),
the usual arithmetic/comparison/logical/bitwise operators, parentheses, and the
RANDOM_INT(min, max) function. Values are integers; comparisons yield 1/0.

STRING content is typed literally (no variable interpolation), matching Hak5.
"""

import random
import re

from . import keymaps


# Expression engine

_TOKEN_RE = re.compile(r'''\s*(?:
      (?P<hex>0[xX][0-9a-fA-F]+)
    | (?P<int>\d+)
    | (?P<hashvar>\#[A-Za-z_][A-Za-z0-9_]*)
    | (?P<var>\$[A-Za-z_][A-Za-z0-9_]*)
    | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op><<|>>|<=|>=|==|!=|&&|\|\||[-+*/%()<>!&|^,])
    )''', re.VERBOSE)

# Operators grouped lowest precedence first.
_PREC = [
    ['||'], ['&&'], ['|'], ['^'], ['&'],
    ['==', '!='], ['<', '<=', '>', '>='], ['<<', '>>'],
    ['+', '-'], ['*', '/', '%'],
]


def _tokenize(s):
    pos, toks = 0, []
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if not m or m.end() == pos:
            if not s[pos:].strip():
                break
            raise ValueError(f'unexpected character near {s[pos:]!r}')
        pos = m.end()
        kind = m.lastgroup
        if kind == 'hex':
            toks.append(('num', int(m.group('hex'), 16)))
        elif kind == 'int':
            toks.append(('num', int(m.group('int'))))
        elif kind == 'var':
            toks.append(('var', m.group('var')[1:]))
        elif kind == 'hashvar':
            toks.append(('var', m.group('hashvar')[1:]))
        elif kind == 'id':
            up = m.group('id').upper()
            if up == 'TRUE':
                toks.append(('num', 1))
            elif up == 'FALSE':
                toks.append(('num', 0))
            else:
                toks.append(('id', m.group('id')))
        else:
            toks.append(('op', m.group().strip()))
    toks.append(('eof', None))
    return toks


class _ExprParser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def _peek(self):
        return self.toks[self.i]

    def _next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self):
        node = self._level(0)
        if self._peek()[0] != 'eof':
            raise ValueError('trailing tokens in expression')
        return node

    def _level(self, lvl):
        if lvl >= len(_PREC):
            return self._unary()
        left = self._level(lvl + 1)
        while self._peek()[0] == 'op' and self._peek()[1] in _PREC[lvl]:
            op = self._next()[1]
            left = ('bin', op, left, self._level(lvl + 1))
        return left

    def _unary(self):
        t = self._peek()
        if t == ('op', '!') or t == ('op', '-'):
            self._next()
            return ('un', t[1], self._unary())
        return self._atom()

    def _atom(self):
        t = self._next()
        if t[0] == 'num':
            return ('num', t[1])
        if t[0] == 'var':
            return ('var', t[1])
        if t == ('op', '('):
            node = self._level(0)
            if self._next() != ('op', ')'):
                raise ValueError('missing closing )')
            return node
        if t[0] == 'id':
            if self._peek() == ('op', '('):
                self._next()
                args = []
                if self._peek() != ('op', ')'):
                    args.append(self._level(0))
                    while self._peek() == ('op', ','):
                        self._next()
                        args.append(self._level(0))
                if self._next() != ('op', ')'):
                    raise ValueError('missing ) in function call')
                return ('call', t[1].upper(), args)
            raise ValueError(f'unexpected identifier {t[1]!r}')
        raise ValueError(f'unexpected token {t[1]!r}')


def compile_expr(s):
    return _ExprParser(_tokenize(s)).parse()


_BINOPS = {
    '+': lambda a, b: a + b, '-': lambda a, b: a - b,
    '*': lambda a, b: a * b,
    '/': lambda a, b: a // b if b else 0, '%': lambda a, b: a % b if b else 0,
    '<<': lambda a, b: a << b, '>>': lambda a, b: a >> b,
    '<': lambda a, b: int(a < b), '<=': lambda a, b: int(a <= b),
    '>': lambda a, b: int(a > b), '>=': lambda a, b: int(a >= b),
    '==': lambda a, b: int(a == b), '!=': lambda a, b: int(a != b),
    '&': lambda a, b: a & b, '|': lambda a, b: a | b, '^': lambda a, b: a ^ b,
}

_FUNCS = {
    'RANDOM_INT': lambda a, b: random.randint(min(a, b), max(a, b)),
    'ABS': abs,
    'MIN': min,
    'MAX': max,
}


def eval_ast(ast, env):
    kind = ast[0]
    if kind == 'num':
        return ast[1]
    if kind == 'var':
        return env.get(ast[1], 0)
    if kind == 'un':
        v = eval_ast(ast[2], env)
        return (0 if v else 1) if ast[1] == '!' else -v
    if kind == 'bin':
        op = ast[1]
        a = eval_ast(ast[2], env)
        if op == '&&':
            return 1 if (a and eval_ast(ast[3], env)) else 0
        if op == '||':
            return 1 if (a or eval_ast(ast[3], env)) else 0
        return _BINOPS[op](a, eval_ast(ast[3], env))
    if kind == 'call':
        fn = _FUNCS.get(ast[1])
        if fn is None:
            raise ValueError(f'unknown function {ast[1]}')
        return fn(*[eval_ast(x, env) for x in ast[2]])
    raise ValueError('bad expression node')


# Statement parser - turns lines into a tree of nodes with control flow
# Node shapes:
#   ('cmd', command, rest, lineno)
#   ('assign', name, expr_ast, lineno)
#   ('if', [(cond_ast, [body]), ...], else_body_or_None, lineno)
#   ('while', cond_ast, [body], lineno)

def _logical_lines(text):
    """Strip blanks and comments, returning [(lineno, stripped_text)]."""
    out, in_block = [], False
    for lineno, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            continue
        head = s.split(None, 1)[0].upper()
        if in_block:
            if head == 'END_REM':
                in_block = False
            continue
        if head == 'REM_BLOCK':
            in_block = True
            continue
        if head == 'REM':
            continue
        out.append((lineno, s))
    return out


class _StmtParser:
    def __init__(self, lines):
        self.lines, self.i = lines, 0

    def _at_end(self):
        return self.i >= len(self.lines)

    def _heads(self):
        parts = self.lines[self.i][1].split(None, 2)
        h1 = parts[0].upper()
        h2 = parts[1].upper() if len(parts) > 1 else ''
        return h1, h2

    def parse_block(self, terminators):
        nodes = []
        while not self._at_end():
            h1, _h2 = self._heads()
            if h1 in terminators:
                return nodes
            lineno, s = self.lines[self.i]
            if h1 == 'IF':
                nodes.append(self._parse_if())
            elif h1 == 'WHILE':
                nodes.append(self._parse_while())
            elif h1 == 'VAR' or s[0] == '$' or s[0] == '#':
                nodes.append(self._parse_assign(lineno, s))
                self.i += 1
            elif h1 == 'DEFINE':
                nodes.append(self._parse_define(lineno, s))
                self.i += 1
            else:
                split = s.split(None, 1)
                rest = split[1] if len(split) > 1 else ''
                nodes.append(('cmd', h1, rest, lineno))
                self.i += 1
        return nodes

    def _cond(self, s):
        a, b = s.find('('), s.rfind(')')
        if a == -1 or b == -1 or b < a:
            raise ValueError(f'malformed condition: {s!r}')
        return compile_expr(s[a + 1:b])

    def _parse_if(self):
        lineno, s = self.lines[self.i]
        self.i += 1
        branches = [(self._cond(s), self.parse_block({'ELSE', 'END_IF'}))]
        else_body = None
        while not self._at_end():
            h1, h2 = self._heads()
            if h1 == 'END_IF':
                self.i += 1
                return ('if', branches, else_body, lineno)
            if h1 == 'ELSE' and h2 == 'IF':
                _, s2 = self.lines[self.i]
                self.i += 1
                branches.append((self._cond(s2), self.parse_block({'ELSE', 'END_IF'})))
            elif h1 == 'ELSE':
                self.i += 1
                else_body = self.parse_block({'END_IF'})
            else:
                break
        raise ValueError(f'unterminated IF at line {lineno}')

    def _parse_while(self):
        lineno, s = self.lines[self.i]
        self.i += 1
        cond = self._cond(s)
        body = self.parse_block({'END_WHILE'})
        if self._at_end():
            raise ValueError(f'unterminated WHILE at line {lineno}')
        self.i += 1  # consume END_WHILE
        return ('while', cond, body, lineno)

    def _parse_assign(self, lineno, s):
        body = s.split(None, 1)[1] if s.split(None, 1)[0].upper() == 'VAR' else s
        if '=' not in body:
            raise ValueError(f'malformed assignment at line {lineno}: {s!r}')
        name, expr = body.split('=', 1)
        name = name.strip()
        if name.startswith('$') or name.startswith('#'):
            name = name[1:]
        if not name:
            raise ValueError(f'missing variable name at line {lineno}')
        return ('assign', name, compile_expr(expr), lineno)

    def _parse_define(self, lineno, s):
        """Parse DEFINE #VARNAME value (Hak5 PayloadStudio extension)."""
        parts = s.split(None, 2)
        if len(parts) < 3:
            raise ValueError(f'malformed DEFINE at line {lineno}: {s!r}')
        name = parts[1].strip()
        if name.startswith('#'):
            name = name[1:]
        if not name:
            raise ValueError(f'missing variable name in DEFINE at line {lineno}')
        return ('assign', name, compile_expr(parts[2]), lineno)


def parse(text):
    """Parse a payload into a node tree. Raises ValueError on syntax errors."""
    return _StmtParser(_logical_lines(text)).parse_block(set())


# Executor

class Interpreter:
    MAX_LOOPS = 100000      # guard against runaway WHILE locking a worker
    MAX_WARNINGS = 200

    def __init__(self, backend):
        self.b = backend
        self.vars = {}
        self.default_delay = 0
        self.char_delay = 0
        self.jitter = 0
        self.prev = None            # last keystroke-producing cmd node
        self.warnings = []
        self.stmt_count = 0
        self.skipped_chars = 0
        self._expr_cache = {}

    # public
    def run(self, text):
        self.exec_nodes(parse(text))

    # node walking
    def exec_nodes(self, nodes):
        for node in nodes:
            self.exec_node(node)

    def exec_node(self, node):
        kind = node[0]
        if kind == 'cmd':
            self.exec_cmd(node)
        elif kind == 'assign':
            self.vars[node[1]] = eval_ast(node[2], self.vars)
        elif kind == 'if':
            _, branches, else_body, _lineno = node
            for cond, body in branches:
                if eval_ast(cond, self.vars):
                    self.exec_nodes(body)
                    return
            if else_body is not None:
                self.exec_nodes(else_body)
        elif kind == 'while':
            _, cond, body, lineno = node
            guard = 0
            while eval_ast(cond, self.vars):
                self.exec_nodes(body)
                guard += 1
                if guard > self.MAX_LOOPS:
                    raise RuntimeError(
                        f'WHILE at line {lineno} exceeded {self.MAX_LOOPS} iterations')

    # command dispatch
    def exec_cmd(self, node):
        _, cmd, rest, lineno = node
        self.stmt_count += 1
        produced = self._dispatch(cmd, rest, lineno)
        if produced and cmd != 'REPEAT':
            self.prev = node
        if self.default_delay:
            self.b.delay(self.default_delay)

    def _dispatch(self, cmd, rest, lineno):
        if cmd in ('STRING', 'STRINGLN'):
            self._type(rest, lineno)
            if cmd == 'STRINGLN':
                self.b.key('ENTER')
            return True
        if cmd == 'DELAY':
            self.b.delay(self._num(rest, lineno, 500))
            return False
        if cmd in ('DEFAULTDELAY', 'DEFAULT_DELAY'):
            self.default_delay = self._num(rest, lineno, 0)
            return False
        if cmd in ('DEFAULTCHARDELAY', 'DEFAULT_CHAR_DELAY', 'STRINGDELAY'):
            self.char_delay = self._num(rest, lineno, 0)
            return False
        if cmd in ('JITTER', 'CHARJITTER'):
            self.jitter = self._num(rest, lineno, 0)
            return False
        if cmd == 'LAYOUT':
            name = rest.strip().lower()
            if keymaps.has_layout(name):
                self.b.set_layout(name)
            else:
                self.warn(lineno, f'unknown layout {name!r}')
            return False
        if cmd == 'REPEAT':
            count = self._num(rest, lineno, 0)
            if self.prev is not None:
                for _ in range(count):
                    self.exec_cmd(self.prev)
            return False
        if cmd in keymaps.MODIFIERS and rest.strip():
            mods, key = [cmd], ''
            for tok in rest.split():
                if tok.upper() in keymaps.MODIFIERS:
                    mods.append(tok.upper())
                else:
                    key = tok
            self.b.combo(mods, key)
            return True
        if cmd in keymaps.MODIFIERS:
            self.b.combo([cmd], '')
            return True
        if cmd in keymaps.NAMED_KEYS:
            self.b.key(cmd)
            return True
        self.warn(lineno, f'unknown command {cmd!r}')
        return False

    # helpers
    def _type(self, text, lineno):
        for ch in text:
            if self.b.char(ch):
                d = self.char_delay
                if self.jitter:
                    d += random.randint(0, self.jitter)
                if d:
                    self.b.delay(d)
            else:
                self.skipped_chars += 1
                self.warn(lineno, f'character {ch!r} not in active layout')

    def _num(self, s, lineno, default):
        s = s.strip()
        if not s:
            return default
        try:
            ast = self._expr_cache.get(s)
            if ast is None:
                ast = compile_expr(s)
                self._expr_cache[s] = ast
            return int(eval_ast(ast, self.vars))
        except Exception as e:
            self.warn(lineno, f'bad expression {s!r}: {e}')
            return default

    def warn(self, lineno, msg):
        if len(self.warnings) < self.MAX_WARNINGS:
            self.warnings.append(f'line {lineno}: {msg}' if lineno else msg)

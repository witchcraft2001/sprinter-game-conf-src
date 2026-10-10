"""Bounded interpreter for the actual GAME_K50 TDF read pipeline.

Supports the combinational expressions, IF/CASE and CLK42 DFFE assignments
used there. Unsupported syntax fails; this is not a MAX+plus II compiler,
netlist/placement simulator or electrical SRAM model. Raster/CPU inputs are
provided by the testbench; source read expressions and register updates execute.
Only the unsigned expressions used in this pipeline are supported; this is not
a general implementation of AHDL typing, signed arithmetic, defaults or resets.
"""
import re
from pathlib import Path

TOKEN = re.compile(r'\s*(B"[01]+"|H"[0-9A-Fa-f]+"|[A-Za-z_]\w*|\d+|\.\.|>=|<=|!=|==|[\[\]().,:;=+!&<>-])')
PRIORITY = {'OR':1, 'XOR':2, '&':3, '==':4, '!=':4, '>=':4, '<=':4, '>':4, '<':4, '+':5, '-':5}


def tokens(source):
    out = []; pos = 0
    while pos < len(source):
        match = TOKEN.match(source, pos)
        if not match:
            if source[pos:].strip(): raise ValueError('Unsupported AHDL near ' + source[pos:pos+50])
            break
        out.append(match[1]); pos = match.end()
    return out


class Parser:
    def __init__(self, source, widths):
        self.words, self.pos, self.widths = tokens(source), 0, widths
        self.assignments = {}

    def peek(self): return self.words[self.pos].upper() if self.pos < len(self.words) else ''

    def take(self, expected=None):
        token = self.words[self.pos]; self.pos += 1
        if expected is not None and token.upper() != expected: raise ValueError('Expected ' + expected + ', got ' + token)
        return token

    def ref(self, name):
        if name.upper() == 'GND': return ('lit', 0, 1)
        if name.upper() == 'VCC': return ('lit', 1, 1)
        lo, width = 0, self.widths.get(name, 1)
        if self.peek() == '[':
            self.take()
            if self.peek() != ']':
                high = int(self.take()); low = high
                if self.peek() == '..': self.take(); low = int(self.take())
                lo, width = low, high-low+1
            self.take(']')
        elif name not in self.widths:
            # Native AHDL single-bit aliases, e.g. MODE03 and DIR_PORT3.
            for base in sorted(self.widths, key=len, reverse=True):
                suffix = name[len(base):] if name.startswith(base) else ''
                if suffix.isdigit(): name, lo, width = base, int(suffix), 1; break
        if name not in self.widths: raise ValueError('Unknown signal ' + name)
        field = ''
        if self.peek() == '.': self.take(); field = '.' + self.take().lower()
        return ('ref', name + field, lo, width)

    def expr(self, minimum=0):
        token = self.take()
        if token == '!': left = ('not', self.expr(6))
        elif token == '(':
            items = [self.expr()]
            while self.peek() == ',': self.take(); items.append(self.expr())
            self.take(')'); left = ('concat', items) if len(items)>1 else items[0]
        elif token.startswith('B"'): left = ('lit', int(token[2:-1],2), len(token)-3)
        elif token.startswith('H"'): left = ('lit', int(token[2:-1],16), 4*(len(token)-3))
        elif token.isdigit(): left = ('lit', int(token), 32)
        else: left = self.ref(token)
        while self.peek() in PRIORITY and PRIORITY[self.peek()] >= minimum:
            op = self.take().upper(); right = self.expr(PRIORITY[op]+1)
            left = ('op', op, left, right)
        return left

    def block(self, conditions=(), stop=()):
        while self.peek() and self.peek() not in stop:
            if self.peek() == 'IF':
                self.take(); test = self.expr(); self.take('THEN')
                self.block(conditions+(test,), ('ELSE','END'))
                if self.peek() == 'ELSE':
                    self.take(); self.block(conditions+(('not', test),), ('END',))
                self.take('END'); self.take('IF'); self.take(';')
            elif self.peek() == 'CASE':
                self.take(); selector = self.expr(); self.take('IS')
                while self.peek() == 'WHEN':
                    self.take(); cases = [self.expr()]
                    while self.peek() == ',': self.take(); cases.append(self.expr())
                    self.take('='); self.take('>')
                    tests = [('op','==',selector,case) for case in cases]
                    test = tests[0]
                    for other in tests[1:]: test = ('op','OR',test,other)
                    self.block(conditions+(test,), ('WHEN','END'))
                self.take('END'); self.take('CASE'); self.take(';')
            else:
                target = self.ref(self.take())
                self.take('='); value = self.expr(); self.take(';')
                if target[0] != 'ref': raise ValueError('Not an assignment target')
                self.assignments.setdefault(target[1], []).append((target[2],target[3],conditions,value))


class ReadProgram:
    def __init__(self, source):
        clean = re.sub(r'--[^\n]*', '', re.sub(r'%.*?%', '', source, flags=re.S))
        decl = clean[clean.index('VARIABLE'):clean.index('\nBEGIN')]
        self.widths = {'CLK42':1, 'CT':6, 'CTH':6, 'CTV':9, 'VCM':3, 'DIR_PORT':8,
                       'VXA':20, 'MXWE':1, 'VAO':16, 'V_WR':4, 'VDM0':8, 'VDM1':8, 'VDM2':8, 'VDM3':8}
        self.registers = set()
        for name, high, kind in re.findall(r'\b(\w+)(?:\[(\d+)\.\.0\])?\s*:\s*(NODE|DFFE|DFF)\s*;', decl):
            self.widths[name] = int(high)+1 if high else 1
            if name.startswith('G_') or name.startswith('MODE') or name == 'VLA':
                if kind in ('DFF','DFFE'): self.registers.add(name)
        read = clean[clean.index('IF (CTH[] == 55)'):clean.index('\n\tV_WE_R\t\t= DFF')]
        # Clock assignments for VLA occur in the shared preamble.
        read += '\n VLA[].clk = CLK42;\n'
        start = clean.index('CASE VCM[1..0] IS')
        end = clean.index('END CASE;', start) + len('END CASE;')
        parser = Parser(read + '\n' + clean[start:end], self.widths)
        parser.block()
        self.assignments = parser.assignments
        self.state = {name:0 for name in self.registers}
        self.inputs = {}; self.cache = {}; self.busy = set()

    @classmethod
    def from_path(cls, path): return cls(Path(path).read_text())

    def evaluate(self, tree):
        kind = tree[0]
        if kind == 'lit': return tree[1], tree[2]
        if kind == 'ref': return (self.get(tree[1]) >> tree[2]) & ((1<<tree[3])-1), tree[3]
        if kind == 'not':
            value, width = self.evaluate(tree[1]); return value ^ ((1<<width)-1), width
        if kind == 'concat':
            value, width = 0, 0
            for item in tree[1]:
                v,w = self.evaluate(item); value = (value<<w)|v; width += w
            return value,width
        op = tree[1]; a,wa = self.evaluate(tree[2]); b,wb = self.evaluate(tree[3])
        if op == '+': return a+b,max(wa,wb)
        if op == '-': return a-b,max(wa,wb)
        if op == '&': return a&b,max(wa,wb)
        if op == 'OR': return a|b,max(wa,wb)
        if op == 'XOR': return a^b,max(wa,wb)
        result = {'==':lambda:a==b, '!=':lambda:a!=b, '>=':lambda:a>=b,
                  '<=':lambda:a<=b, '>':lambda:a>b, '<':lambda:a<b}[op]()
        return int(result),1

    def driver(self, name):
        """Evaluate a D input without replacing its old Q state."""
        value = 0; found = False
        for low,width,conditions,tree in self.assignments.get(name,[]):
            if all(self.evaluate(test)[0] for test in conditions):
                bits = (1<<width)-1
                v = self.evaluate(tree)[0] & bits
                value = (value & ~(bits<<low)) | (v<<low)
                found = True
        if not found: raise ValueError('Undriven signal '+name)
        return value

    def get(self, name):
        if name in self.state: return self.state[name]
        if name in self.inputs: return self.inputs[name]
        if name in self.cache: return self.cache[name]
        if name in self.busy: raise ValueError('Combinational loop at '+name)
        self.busy.add(name)
        try: value = self.driver(name)
        finally: self.busy.remove(name)
        self.cache[name] = value
        return value

    def set_inputs(self, **values):
        self.inputs.update(values); self.cache.clear()

    def edge(self):
        # Snapshot all D/enable expressions before committing any register.
        next_state = self.state.copy()
        for name in self.registers:
            if self.get(name+'.clk') != 1: raise ValueError('Only CLK42 rising-edge registers supported: '+name)
            enabled = self.get(name+'.ena') if name+'.ena' in self.assignments else 1
            if enabled:
                driver = name+'.d' if name+'.d' in self.assignments else name
                value = self.driver(driver)
                next_state[name] = value & ((1<<self.widths[name])-1)
        self.state = next_state; self.cache.clear()

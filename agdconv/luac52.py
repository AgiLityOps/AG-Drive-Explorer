"""Minimal Lua 5.2 bytecode reader + tiny evaluator (our own code; no Lua runtime, no decompiler).

It loads a precompiled chunk (32- or 64-bit size_t), then runs only the main function with a small subset
of the VM: constants, globals, table constructors, arithmetic and string concatenation. Calls return nil,
closures become placeholders, and loops are cut off after a step limit. That is enough to read
simple data scripts such as "settings = { size = 100, scale = base * 2 / 3 }". It also exposes every string constant
in every function prototype (used to read GLSL source embedded in shader scripts)."""
import struct

class LuaFunction:
    def __repr__(self): return '<lua function>'

class Proto:
    pass

class Reader:
    def __init__(self, data):
        if data[:4] != b'\x1bLua' or data[4] != 0x52:
            raise ValueError('not a Lua 5.2 chunk')
        fmt, endian, s_int, s_size, s_ins, s_num, integral = data[5:12]
        if fmt != 0 or s_ins != 4 or s_num != 8 or integral != 0 or s_int != 4:
            raise ValueError('unsupported Lua chunk layout')
        if data[12:18] != b'\x19\x93\r\n\x1a\n':
            raise ValueError('bad Lua chunk tail')
        self.e = '<' if endian == 1 else '>'
        self.size_t = 'I' if s_size == 4 else 'Q'
        self.s_size = s_size
        self.d = data; self.p = 18
    def u8(self):
        v = self.d[self.p]; self.p += 1; return v
    def i32(self):
        v = struct.unpack_from(self.e + 'i', self.d, self.p)[0]; self.p += 4; return v
    def sz(self):
        v = struct.unpack_from(self.e + self.size_t, self.d, self.p)[0]; self.p += self.s_size; return v
    def string(self):
        n = self.sz()
        if n == 0: return None
        s = self.d[self.p:self.p + n - 1]; self.p += n
        return s.decode('latin1')
    def function(self):
        f = Proto()
        f.linedefined = self.i32(); f.lastline = self.i32()
        f.numparams = self.u8(); f.is_vararg = self.u8(); f.maxstack = self.u8()
        n = self.i32(); f.code = list(struct.unpack_from(self.e + '%dI' % n, self.d, self.p)); self.p += 4 * n
        n = self.i32(); f.k = []
        for _ in range(n):
            t = self.u8()
            if t == 0: f.k.append(None)
            elif t == 1: f.k.append(bool(self.u8()))
            elif t == 3:
                f.k.append(struct.unpack_from(self.e + 'd', self.d, self.p)[0]); self.p += 8
            elif t == 4: f.k.append(self.string())
            else: raise ValueError('bad constant type %d' % t)
        n = self.i32(); f.protos = [self.function() for _ in range(n)]
        n = self.i32(); f.upvals = [(self.u8(), self.u8()) for _ in range(n)]
        f.source = self.string()
        n = self.i32(); self.p += 4 * n                       # line info
        n = self.i32()
        for _ in range(n): self.string(); self.i32(); self.i32()   # local vars
        n = self.i32()
        for _ in range(n): self.string()                       # upvalue names
        return f

def load(data):
    r = Reader(data); return r.function()

def all_strings(proto):
    out = [k for k in proto.k if isinstance(k, str)]
    for p in proto.protos: out += all_strings(p)
    return out

def _num(v):
    if isinstance(v, bool) or v is None: raise TypeError
    if isinstance(v, str): return float(v)
    return v

def run_main(proto, max_steps=200000):
    """Execute the main chunk with a restricted VM; returns the globals dict (Lua tables -> Python dicts)."""
    G = {}
    R = [None] * 256
    pc = 0; steps = 0; top = 0
    code = proto.code; K = proto.k
    def RK(x): return K[x & 0xFF] if x & 0x100 else R[x]
    def arith(op, a, b):
        try:
            a = _num(a); b = _num(b)
            if op == 13: return a + b
            if op == 14: return a - b
            if op == 15: return a * b
            if op == 16: return a / b
            if op == 17: return a - (a // b) * b
            if op == 18: return a ** b
        except Exception:
            return None
    while pc < len(code) and steps < max_steps:
        steps += 1
        i = code[pc]; pc += 1
        op = i & 0x3F; A = (i >> 6) & 0xFF; C = (i >> 14) & 0x1FF; B = (i >> 23) & 0x1FF
        Bx = i >> 14; sBx = Bx - 131071
        if op == 0: R[A] = R[B]
        elif op == 1: R[A] = K[Bx]
        elif op == 2: R[A] = K[code[pc] >> 6]; pc += 1
        elif op == 3:
            R[A] = bool(B)
            if C: pc += 1
        elif op == 4:
            for j in range(A, A + B + 1): R[j] = None
        elif op == 5: R[A] = G if B == 0 else None
        elif op == 6:
            k = RK(C); R[A] = G.get(k) if B == 0 else None
        elif op == 7:
            t = R[B]; k = RK(C); R[A] = t.get(k) if isinstance(t, dict) else None
        elif op == 8:
            if A == 0: G[RK(B)] = RK(C)
        elif op == 9: pass
        elif op == 10:
            t = R[A]
            if isinstance(t, dict): t[RK(B)] = RK(C)
        elif op == 11: R[A] = {}
        elif op == 12:
            t = R[B]; R[A + 1] = t; R[A] = t.get(RK(C)) if isinstance(t, dict) else None
        elif 13 <= op <= 18: R[A] = arith(op, RK(B), RK(C))
        elif op == 19:
            try: R[A] = -_num(R[B])
            except Exception: R[A] = None
        elif op == 20: R[A] = R[B] is None or R[B] is False
        elif op == 21:
            v = R[B]
            R[A] = len(v) if isinstance(v, str) else (sum(1 for k in v if isinstance(k, (int, float))) if isinstance(v, dict) else None)
        elif op == 22:
            parts = R[B:C + 1]
            try: R[A] = ''.join(p if isinstance(p, str) else _fmt(p) for p in parts)
            except Exception: R[A] = None
        elif op == 23: pc += sBx
        elif op in (24, 25, 26):
            a = RK(B); b = RK(C)
            try: res = (a == b) if op == 24 else ((a < b) if op == 25 else (a <= b))
            except Exception: res = False
            if res != bool(A): pc += 1
        elif op == 27:
            truthy = not (R[A] is None or R[A] is False)
            if truthy != bool(C): pc += 1
        elif op == 28:
            truthy = not (R[B] is None or R[B] is False)
            if truthy != bool(C): pc += 1
            else: R[A] = R[B]
        elif op in (29, 30):
            # function calls are not executed (print etc.); results are nil
            if C == 0: top = A
            else:
                for j in range(A, A + C - 1): R[j] = None
            if op == 30: break
        elif op == 31: break
        elif op in (32, 33, 34, 35): pass      # loops: not needed for data scripts; just fall through
        elif op == 36:
            t = R[A]; n = B if B else max(0, top - A - 1)
            c = C
            if c == 0: c = code[pc] >> 6; pc += 1
            if isinstance(t, dict):
                for j in range(1, n + 1): t[(c - 1) * 50 + j] = R[A + j]
        elif op == 37: R[A] = LuaFunction()
        elif op == 38:
            if B == 0: top = A
            else:
                for j in range(A, A + B - 1): R[j] = None
        elif op == 39: pass
    return G

def _fmt(v):
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v)

def to_py(v):
    """Lua table dict -> list when it has keys 1..n only, recursively; integral floats -> int."""
    if isinstance(v, dict):
        if v and all(isinstance(k, (int, float)) and not isinstance(k, bool) for k in v):
            ks = sorted(v)
            if ks == list(range(1, len(ks) + 1)): return [to_py(v[k]) for k in ks]
        return {(_fmt(k) if not isinstance(k, str) else k): to_py(x) for k, x in v.items()}
    if isinstance(v, float) and v.is_integer() and abs(v) < 2**53: return int(v)
    return v

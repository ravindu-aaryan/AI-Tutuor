"""Arithmetic understanding for the offline brain.

Finds calculations printed in the textbook (``3/5 + 1/5 = 4/5``, ``24 × 3``, ``2.5 − 0.75``), generates new
calculations *of the same kind* at a requested difficulty, solves them exactly with step-by-step working, and
recognises the classic mistakes (adding denominators, wrong operation, ignoring order of operations, ...).
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

_NUM = r"\d+ \d+/\d+|\d+/\d+|\d+\.\d+|\d+"
_OP = r"\s*[+×*÷−]\s*|\s+[-x:]\s+"
EXPR_RE = re.compile(rf"(?<![\w./])((?:{_NUM})(?:(?:{_OP})(?:{_NUM})){{1,3}})(?:\s*=\s*({_NUM})?)?(?![\w/])")

OP_SYMBOL = {"+": "+", "-": "−", "−": "−", "×": "×", "x": "×", "*": "×", "÷": "÷", ":": "÷"}
OP_WORD = {"+": "add", "−": "subtract", "×": "multiply", "÷": "divide"}
OP_PAST = {"+": "added", "−": "subtracted", "×": "multiplied", "÷": "divided"}


@dataclass
class Operand:
    value: Fraction
    kind: str  # int | frac | mixed | dec
    places: int = 0  # decimal places for dec

    @property
    def text(self) -> str:
        return format_value(self.value, self.kind, self.places)


@dataclass
class Expression:
    operands: list[Operand]
    ops: list[str]  # normalised symbols: + − × ÷

    @property
    def text(self) -> str:
        parts = [self.operands[0].text]
        for op, operand in zip(self.ops, self.operands[1:]):
            parts += [op, operand.text]
        return " ".join(parts)

    @property
    def kinds(self) -> set[str]:
        return {o.kind for o in self.operands}

    @property
    def is_fraction(self) -> bool:
        return bool(self.kinds & {"frac", "mixed"})

    def value(self) -> Fraction:
        return evaluate([o.value for o in self.operands], self.ops)


# --------------------------------------------------------------------------- parsing & evaluation


def parse_operand(token: str) -> Operand:
    token = token.strip()
    if " " in token:
        whole, frac = token.split()
        return Operand(int(whole) + Fraction(frac), "mixed")
    if "/" in token:
        n, d = token.split("/")
        return Operand(Fraction(int(n), int(d)), "frac")
    if "." in token:
        return Operand(Fraction(Decimal(token)), "dec", len(token.split(".")[1]))
    return Operand(Fraction(int(token)), "int")


def parse_expression(text: str) -> Expression | None:
    m = EXPR_RE.search(text)
    if not m:
        return None
    return _build(m.group(1))


def _build(body: str) -> Expression | None:
    tokens = re.split(rf"({_OP})", body)
    try:
        operands = [parse_operand(t) for t in tokens[0::2]]
    except (ValueError, ZeroDivisionError):
        return None
    ops = [OP_SYMBOL[t.strip()] for t in tokens[1::2]]
    if any(o.kind == "frac" and o.value.denominator == 1 and o.value.numerator > 50 for o in operands):
        return None
    return Expression(operands, ops)


def find_expressions(text: str) -> list[tuple[Expression, str | None]]:
    """Calculations in a text, with the printed answer if there was one. Skips things like dates and pages."""
    out: list[tuple[Expression, str | None]] = []
    seen: set[str] = set()
    for m in EXPR_RE.finditer(text):
        expr = _build(m.group(1))
        if expr is None or expr.text in seen:
            continue
        # A lone "a/b" pair isn't a calculation; nor are huge numbers (years, phone numbers...).
        if any(o.value > 100000 for o in expr.operands):
            continue
        if "÷" in expr.ops and any(o.value == 0 for o in expr.operands[1:]):
            continue
        seen.add(expr.text)
        out.append((expr, m.group(2)))
    return out


def apply(a: Fraction, op: str, b: Fraction) -> Fraction:
    if op == "+":
        return a + b
    if op == "−":
        return a - b
    if op == "×":
        return a * b
    if b == 0:
        raise ZeroDivisionError
    return a / b


def evaluate(values: list[Fraction], ops: list[str], precedence: bool = True) -> Fraction:
    values, ops = list(values), list(ops)
    if precedence:
        i = 0
        while i < len(ops):
            if ops[i] in "×÷":
                values[i : i + 2] = [apply(values[i], ops[i], values[i + 1])]
                ops.pop(i)
            else:
                i += 1
    result = values[0]
    for op, v in zip(ops, values[1:]):
        result = apply(result, op, v)
    return result


# --------------------------------------------------------------------------- formatting


def format_value(value: Fraction, kind: str, places: int = 0) -> str:
    if kind == "dec" or (kind == "int" and value.denominator != 1 and _terminates(value)):
        return decimal_text(value)
    if value.denominator == 1:
        return str(value.numerator)
    if kind == "mixed" and abs(value) > 1:
        whole = int(value)
        rest = abs(value - whole)
        return f"{whole} {rest.numerator}/{rest.denominator}"
    return f"{value.numerator}/{value.denominator}"


def _terminates(value: Fraction) -> bool:
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


def decimal_text(value: Fraction) -> str:
    if not _terminates(value):
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    text = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def answer_forms(value: Fraction, expr: Expression) -> tuple[str, list[str]]:
    """Main answer text and other acceptable ways of writing it."""
    if expr.is_fraction:
        main = format_value(value, "mixed" if "mixed" in expr.kinds else "frac")
        alts = {format_value(value, "frac"), format_value(value, "mixed")}
        if _terminates(value):
            alts.add(decimal_text(value))
        alts.discard(main)
        return main, sorted(alts)
    if value.denominator != 1 and not _terminates(value):
        return f"{value.numerator}/{value.denominator}", [decimal_text(value)]
    return decimal_text(value) if value.denominator != 1 else str(value.numerator), []


# --------------------------------------------------------------------------- generation


def generate_like(template: Expression, difficulty: int, rng: random.Random) -> Expression:
    """A new calculation of the same shape as ``template``, scaled to difficulty 1..5."""
    ops = list(template.ops)
    kinds = [o.kind for o in template.operands]
    if difficulty >= 5 and len(ops) == 1 and not template.is_fraction:
        ops.append(rng.choice(["+", "−"] if ops[0] in "×÷" else ["×"]))
        kinds.append(kinds[-1])
    elif difficulty <= 2 and len(ops) > 1:
        ops, kinds = ops[:1], kinds[:2]

    digits = max(len(str(int(abs(o.value)))) for o in template.operands)
    places = max((o.places for o in template.operands if o.kind == "dec"), default=1)
    same_den = difficulty <= 2 or (difficulty <= 3 and _same_denominators(template))

    for _ in range(200):
        den = rng.choice([2, 3, 4, 5, 6, 8, 10] if difficulty <= 3 else [3, 4, 5, 6, 7, 8, 9, 10, 12])
        operands = [
            _random_operand(kind, difficulty, digits, places, den if same_den else None, rng) for kind in kinds
        ]
        expr = Expression(operands, ops)
        _make_friendly(expr, rng)
        try:
            v = expr.value()
        except ZeroDivisionError:
            continue
        if v < 0 or (expr.is_fraction and v == 0):
            continue
        if "÷" in ops and not expr.is_fraction and kinds[0] == "int" and v.denominator != 1:
            continue
        return expr
    return template


def _same_denominators(expr: Expression) -> bool:
    dens = {o.value.denominator for o in expr.operands if o.kind in ("frac", "mixed")}
    return len(dens) == 1


def _random_operand(kind: str, difficulty: int, digits: int, places: int, den: int | None, rng: random.Random) -> Operand:
    if kind in ("frac", "mixed"):
        d = den or rng.choice([2, 3, 4, 5, 6, 8, 9, 10, 12])
        # Numerators coprime with the denominator, so the fraction is shown exactly as generated (3/6 would become 1/2).
        n = rng.choice([k for k in range(1, d) if math.gcd(k, d) == 1])
        value = Fraction(n, d)
        if kind == "mixed":
            value += rng.randint(1, 3 if difficulty <= 3 else 6)
        return Operand(value, kind)
    if kind == "dec":
        p = 1 if difficulty <= 2 else max(1, min(places, 2))
        top = 10 ** max(1, min(digits, 2) + (1 if difficulty >= 4 else 0))
        value = Fraction(rng.randint(1, top * 10**p - 1), 10**p)
        return Operand(value, "dec", p)
    d = {1: 1, 2: max(1, min(digits, 2)), 3: max(1, digits), 4: digits + 1, 5: digits + 1}[max(1, min(5, difficulty))]
    low = 2 if d == 1 else 10 ** (d - 1)
    return Operand(Fraction(rng.randint(low, 10**d - 1)), "int")


def _make_friendly(expr: Expression, rng: random.Random) -> None:
    """Keep subtractions non-negative and whole-number divisions exact."""
    for i, op in enumerate(expr.ops):
        a, b = expr.operands[i], expr.operands[i + 1]
        if op == "−" and len(expr.ops) == 1 and a.value < b.value:
            expr.operands[i], expr.operands[i + 1] = b, a
        if op == "÷" and a.kind == "int" and b.kind == "int":
            divisor = max(2, int(b.value) % 12 or 2)
            b.value = Fraction(divisor)
            a.value = Fraction(divisor * rng.randint(2, max(3, int(a.value) // divisor or 3)))


# --------------------------------------------------------------------------- working and mistakes


def solution_steps(expr: Expression) -> list[str]:
    """Step-by-step working, in the way a school textbook would show it."""
    if len(expr.ops) == 1 and expr.is_fraction:
        return _fraction_steps(expr)
    steps: list[str] = []
    values = [o.value for o in expr.operands]
    ops = list(expr.ops)
    kind = "dec" if "dec" in expr.kinds else "int"
    if len(ops) > 1 and any(o in "×÷" for o in ops) and any(o in "+−" for o in ops):
        steps.append("Do × and ÷ before + and −.")
    # multiply/divide first
    i = 0
    while i < len(ops):
        if ops[i] in "×÷":
            r = apply(values[i], ops[i], values[i + 1])
            steps.append(f"{format_value(values[i], kind)} {ops[i]} {format_value(values[i + 1], kind)} = {format_value(r, kind)}")
            values[i : i + 2] = [r]
            ops.pop(i)
        else:
            i += 1
    result = values[0]
    for op, v in zip(ops, values[1:]):
        r = apply(result, op, v)
        steps.append(f"{format_value(result, kind)} {op} {format_value(v, kind)} = {format_value(r, kind)}")
        result = r
    if kind == "dec" and any(o in "+−" for o in expr.ops):
        steps.insert(0, "Line up the decimal points, then work column by column.")
    return steps


def _fraction_steps(expr: Expression) -> list[str]:
    a, b = expr.operands
    op = expr.ops[0]
    x, y = a.value, b.value
    steps: list[str] = []
    if "mixed" in expr.kinds:
        steps.append(f"Change mixed numbers to improper fractions: {a.text} = {_improper(x)}, {b.text} = {_improper(y)}.")
    if op in "+−":
        if x.denominator == y.denominator:
            d = x.denominator
            n = x.numerator + y.numerator if op == "+" else x.numerator - y.numerator
            steps.append(f"The denominators are the same ({d}), so keep the denominator and {OP_WORD[op]} the numerators: "
                         f"{x.numerator} {op} {y.numerator} = {n}.")
            steps.append(f"That gives {n}/{d}.")
        else:
            lcd = math.lcm(x.denominator, y.denominator)
            nx, ny = x.numerator * lcd // x.denominator, y.numerator * lcd // y.denominator
            n = nx + ny if op == "+" else nx - ny
            steps.append(f"The denominators are different, so find a common denominator: the lowest common multiple of "
                         f"{x.denominator} and {y.denominator} is {lcd}.")
            steps.append(f"Rewrite: {_improper(x)} = {nx}/{lcd} and {_improper(y)} = {ny}/{lcd}.")
            steps.append(f"Now {OP_WORD[op]} the numerators: {nx} {op} {ny} = {n}, giving {n}/{lcd}.")
            d = lcd
        raw = Fraction(n, d) if d else Fraction(0)
        unsimplified = f"{n}/{d}"
    elif op == "×":
        n, d = x.numerator * y.numerator, x.denominator * y.denominator
        steps.append(f"Multiply the numerators ({x.numerator} × {y.numerator} = {n}) and the denominators "
                     f"({x.denominator} × {y.denominator} = {d}), giving {n}/{d}.")
        raw, unsimplified = Fraction(n, d), f"{n}/{d}"
    else:
        steps.append(f"Dividing by {_improper(y)} is the same as multiplying by its reciprocal {y.denominator}/{y.numerator}.")
        n, d = x.numerator * y.denominator, x.denominator * y.numerator
        steps.append(f"{_improper(x)} × {y.denominator}/{y.numerator} = {n}/{d}.")
        raw, unsimplified = Fraction(n, d), f"{n}/{d}"
    final = format_value(raw, "mixed" if "mixed" in expr.kinds else "frac")
    if final != unsimplified:
        steps.append(f"Simplify: {unsimplified} = {final}.")
    return steps


def _improper(v: Fraction) -> str:
    return f"{v.numerator}/{v.denominator}"


def diagnose(expr: Expression, student_value: float) -> str | None:
    """Name the mistake that produces the student's (wrong) answer, if it is a well-known one."""

    def same(v: Fraction | float) -> bool:
        return abs(float(v) - student_value) < 1e-6

    ops = expr.ops
    vals = [o.value for o in expr.operands]
    if len(ops) == 1 and expr.is_fraction:
        x, y = vals
        op = ops[0]
        if op in "+−":
            n = x.numerator + y.numerator if op == "+" else x.numerator - y.numerator
            d = x.denominator + y.denominator if op == "+" else x.denominator - y.denominator
            if d and same(Fraction(n, d)):
                return (f"You {OP_PAST[op]} the denominators too. Only the numerators are {OP_PAST[op]}; the denominator "
                        "tells you the size of the pieces, and that doesn't change.")
            if x.denominator != y.denominator and any(same(Fraction(n, dd)) for dd in (x.denominator, y.denominator)):
                return (f"You {OP_PAST[op]} the numerators without first making the denominators the same. The pieces must be "
                        "the same size before you can count them together.")
        if op == "÷" and same(x * y):
            return "You multiplied instead of dividing. To divide by a fraction, multiply by its reciprocal (flip the second fraction)."
        if op == "÷" and y != 0 and x != 0 and same(1 / x * y):
            return "You flipped the wrong fraction. Keep the first fraction, and flip only the one you are dividing by."
        if op == "×" and x.denominator == y.denominator and same(Fraction(x.numerator * y.numerator, x.denominator)):
            return "You kept the denominator the same. When multiplying fractions, multiply the denominators too."
    if len(ops) > 1:
        try:
            if same(evaluate(vals, ops, precedence=False)) and not same(expr.value()):
                return "You worked from left to right. Remember to do × and ÷ before + and −."
        except ZeroDivisionError:
            pass
    for i, op in enumerate(ops):
        for other in "+−×÷":
            if other == op:
                continue
            try:
                if same(evaluate(vals, ops[:i] + [other] + ops[i + 1 :])):
                    return f"You {OP_PAST[other]} instead of {OP_WORD[op]}ing." if op != "−" else f"You {OP_PAST[other]} instead of subtracting."
            except ZeroDivisionError:
                continue
    if len(ops) == 1 and ops[0] == "−" and same(vals[1] - vals[0]):
        return "You subtracted the numbers the wrong way round."
    right = float(expr.value())
    if right and abs(student_value - right) == 1:
        return "Very close - your answer is off by one. Check your counting or carrying."
    if right and student_value and (abs(student_value / right) in (10, 100, 0.1, 0.01)):
        return "The digits are right but the place value isn't. Check where the decimal point or the zeros go."
    return None


# --------------------------------------------------------------------------- pictures


def fraction_bar(value: Fraction, pieces: int | None = None) -> str | None:
    """Bars of ``pieces`` squares (default: the fraction's own denominator)."""
    pieces = pieces or value.denominator
    if pieces > 12 or value < 0 or value > 3 or (value * pieces).denominator != 1:
        return None
    whole, rest = divmod(int(value * pieces), pieces)
    bars = ["■" * pieces] * whole
    if rest:
        bars.append("■" * rest + "□" * (pieces - rest))
    return " ".join(bars)


def picture(expr: Expression) -> str | None:
    """A text picture of the calculation (fraction bars or counters), when the numbers are small enough."""
    if expr.is_fraction and len(expr.ops) == 1 and expr.ops[0] in "+−":
        rows = []
        pieces = math.lcm(*(o.value.denominator for o in expr.operands))
        for o in expr.operands:
            bar = fraction_bar(o.value, pieces)
            if bar is None:
                return None
            rows.append(f"{o.text:>6}  {bar}")
        result = expr.value()
        bar = fraction_bar(result, pieces)
        if bar is None:
            return None
        rows.append(f"{format_value(result, 'frac'):>6}  {bar}   ← the answer")
        return "Each ■ is one piece; □ is an empty piece.\n\n```\n" + "\n".join(rows) + "\n```"
    if expr.kinds == {"int"} and len(expr.ops) == 1 and expr.ops[0] in "+−" and max(o.value for o in expr.operands) <= 20:
        a, b = (int(o.value) for o in expr.operands)
        if expr.ops[0] == "+":
            return f"```\n{'●' * a} + {'●' * b} = {'●' * (a + b)}  ({a + b})\n```"
        return f"```\n{'●' * (a - b)}{'○' * b}  ({a} take away {b} leaves {a - b})\n```"
    if expr.kinds == {"int"} and len(expr.ops) == 1 and expr.ops[0] == "×" and max(o.value for o in expr.operands) <= 10:
        a, b = (int(o.value) for o in expr.operands)
        rows = "\n".join("● " * b for _ in range(a))
        return f"{a} rows of {b}:\n\n```\n{rows}\n```\n{a} × {b} = {a * b}"
    return None

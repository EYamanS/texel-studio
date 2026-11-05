"""
The compact text syntax for drawing operations, with macros, loops and expressions.

    ellipse 32 32 12 11 #ffffff t        one operation per line, arguments separated by spaces
    fillr [ellipse,32,40,9,5] #ca2297    lists use [a,b,c], hex colors may be written directly
    rows 10 20 ["..ab..","_cdd_"]        quoted strings for pixel rows
    // comment                            everything after // is ignored

Macros, loops and expressions are expanded before parsing:

    macro star $x $y $color               define a macro (stored in paint_work/lib/ and reusable in later runs)
      star $x $y 7 3 5 -90 $color
    endmacro
    use star 10 10 #ffd23c                call a macro ($1, $2 ... or the parameter names inside the body)

    for i 0 3                             loop (inclusive); optional 4th number = step
      disc ${12+8*$i} 40 3 #e04040        ${...} is an expression (sin, cos in degrees, sqrt, pi, min, max, abs, round, int, hyp)
    endfor

Dictionaries in text syntax need no quotes: {#ff0000:#00ff00}.
"""

import json
import math
import re

from texel_paint import store

LIB = store.WORK / "lib"
MAX_MACRO_DEPTH = 12


def tokenize(line: str) -> list[str]:
    """Split on spaces, but keep [..], {..} and "..." together."""
    tokens, current, depth, quoted = [], "", 0, False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        if not quoted:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            if ch.isspace() and depth == 0:
                if current:
                    tokens.append(current)
                    current = ""
                continue
        current += ch
    if current:
        tokens.append(current)
    return tokens


def _value(token: str):
    if token in ("t", "true"):
        return True
    if token in ("f", "false"):
        return False
    if token[:1] in "[{":
        text = re.sub(r"#[0-9a-fA-F]{3,8}\b", lambda m: '"%s"' % m.group(0), token)
        text = re.sub(r'(?<=[\[,:])\s*([A-Za-z_][\w-]*)\s*(?=[,\]\}])',
                      lambda m: m.group(0) if m.group(1) in ("true", "false", "null") else '"%s"' % m.group(1), text)
        return json.loads(text)
    try:
        return json.loads(token)
    except Exception:
        return token


# ───────────────────────── Expressions ─────────────────────────

_MATH = {"sin": lambda a: math.sin(math.radians(a)), "cos": lambda a: math.cos(math.radians(a)),
         "sqrt": math.sqrt, "pi": math.pi, "min": min, "max": max, "abs": abs, "round": round, "int": int,
         "hyp": math.hypot}
_SAFE_EXPRESSION = re.compile(r"^[\w\s+\-*/%().,<>=!]*$")


def _number(value):
    try:
        return float(value) if "." in str(value) else int(value)
    except (TypeError, ValueError):
        return None


def _format(value) -> str:
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else ("%.4f" % value).rstrip("0").rstrip(".")
    return str(value)


def _evaluate(expression: str, env: dict):
    if not _SAFE_EXPRESSION.match(expression):
        raise ValueError(f"Expression not allowed: {expression}")
    names = dict(_MATH)
    for key, value in env.items():
        number = _number(value)
        if number is not None and re.match(r"^[A-Za-z_]\w*$", str(key)):
            names[key] = number
    return eval(expression, {"__builtins__": {}}, names)


def _substitute(line: str, env: dict) -> str:
    for key in sorted(env, key=lambda k: -len(str(k))):          # $name first, then ${expression}
        line = re.sub(r"\$" + re.escape(str(key)) + r"(?![A-Za-z0-9_])", lambda m, k=key: _format(env[k]), line)
    return re.sub(r"\$\{([^{}]+)\}", lambda m: _format(_evaluate(m.group(1), env)), line)


# ───────────────────────── Macros and loops ─────────────────────────

def load_macros() -> dict[str, tuple[list[str], list[str]]]:
    macros = {}
    if LIB.exists():
        for path in LIB.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            macros[path.stem] = (data["params"], data["body"])
    return macros


def _block_end(lines: list[str], start: int, opener: str, closer: str) -> int:
    depth = 1
    for j in range(start + 1, len(lines)):
        text = lines[j].strip()
        if text.startswith(opener + " "):
            depth += 1
        elif text == closer or text.startswith(closer + " "):
            depth -= 1
            if depth == 0:
                return j
    raise ValueError(f"'{opener}' without matching '{closer}'")


def _expand(lines: list[str], env: dict, macros: dict, depth: int = 0) -> list[str]:
    if depth > MAX_MACRO_DEPTH:
        raise ValueError("Macros nested too deeply")
    out, i = [], 0
    while i < len(lines):
        text = lines[i].strip()
        if text.startswith("for "):
            end = _block_end(lines, i, "for", "endfor")
            parts = tokenize(_substitute(text, env))
            var, first, last = parts[1], int(_evaluate(parts[2], env)), int(_evaluate(parts[3], env))
            step = int(_evaluate(parts[4], env)) if len(parts) > 4 else 1
            for value in range(first, last + (1 if step > 0 else -1), step):
                out += _expand(lines[i + 1:end], {**env, var: value}, macros, depth + 1)
            i = end
        elif text.startswith("use "):
            parts = tokenize(_substitute(text, env))
            name, args = parts[1], parts[2:]
            if name not in macros:
                raise ValueError(f"Unknown macro '{name}' (known: {', '.join(sorted(macros)) or 'none'})")
            params, body = macros[name]
            inner = dict(env)
            for k, value in enumerate(args, 1):
                inner[str(k)] = value
                if k <= len(params):
                    inner[params[k - 1].lstrip("$")] = value
            out += _expand(body, inner, macros, depth + 1)
        else:
            out.append(_substitute(lines[i], env) if "$" in lines[i] else lines[i])
        i += 1
    return out


def preprocess(text: str) -> str:
    """Strip comments, store `macro` definitions and expand use/for/${...}. Returns plain operation lines."""
    lines = [l.split("//")[0].rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l.strip()]
    if not any(l.lstrip().startswith(("macro ", "use ", "for ")) or "$" in l for l in lines):
        return "\n".join(lines)
    macros, rest, i = load_macros(), [], 0
    while i < len(lines):
        text_line = lines[i].strip()
        if text_line.startswith("macro "):
            end = _block_end(lines, i, "macro", "endmacro")
            parts = text_line.split()
            LIB.mkdir(parents=True, exist_ok=True)
            (LIB / f"{parts[1]}.json").write_text(json.dumps({"params": parts[2:], "body": lines[i + 1:end]}),
                                                  encoding="utf-8")
            macros[parts[1]] = (parts[2:], lines[i + 1:end])
            i = end
        else:
            rest.append(lines[i])
        i += 1
    return "\n".join(_expand(rest, {}, macros))


# ───────────────────────── Parsing ─────────────────────────

def parse_text_ops(text: str) -> list:
    ops = []
    for line in preprocess(text).splitlines():
        line = line.split("//")[0].strip()
        if not line:
            continue
        tokens = tokenize(line)
        ops.append([tokens[0]] + [_value(t) for t in tokens[1:]])
    return ops


def parse_ops(raw: str) -> list:
    """Text syntax, or a JSON list like [["rect",0,0,7,7,1],["px",3,3,2]]."""
    text = raw.strip()
    return json.loads(text) if text.startswith("[") else parse_text_ops(raw)

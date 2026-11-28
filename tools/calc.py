"""Calculator and unit conversion (Tier 0). No eval(): expressions are parsed with `ast` and only
numbers and arithmetic operators are allowed."""
import ast
import math
import operator
import re

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"sqrt": math.sqrt, "round": round, "abs": abs, "log": math.log10, "ln": math.log,
          "sin": lambda x: math.sin(math.radians(x)), "cos": lambda x: math.cos(math.radians(x)),
          "tan": lambda x: math.tan(math.radians(x))}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and len(node.args) == 1:
        return _FUNCS[node.func.id](_eval(node.args[0]))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("unsupported")


def _normalise(expr: str) -> str:
    e = expr.lower().replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    e = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"(\1/100)*", e)       # 15% of 240
    e = re.sub(r"(\d+(?:\.\d+)?)\s*percent\s*of\s*", r"(\1/100)*", e)
    e = re.sub(r"square root of\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", e)
    for word, sym in (("plus", "+"), ("minus", "-"), ("times", "*"), ("multiplied by", "*"), ("x", "*"),
                      ("divided by", "/"), ("over", "/"), ("to the power of", "**"), ("squared", "**2"),
                      ("cubed", "**3")):
        e = re.sub(rf"\b{word}\b", sym, e)
    return e.replace("%", "/100")


def fmt(x: float) -> str:
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        raise ValueError("not a number")
    if abs(x - round(x)) < 1e-9 and abs(x) < 1e15:
        return f"{int(round(x)):,}"
    return f"{x:.4g}" if abs(x) < 1e6 else f"{x:,.0f}"


def calculate(expression: str) -> str:
    try:
        value = _eval(ast.parse(_normalise(expression), mode="eval"))
        return f"The answer is {fmt(value)}."
    except ZeroDivisionError:
        return "You can't divide by zero."
    except Exception:
        return "I couldn't work that out. Try saying it as a simple sum."


# ---------------------------------------------------------------- units
# factor to the base unit of each dimension
_UNITS = {
    "length": {"m": 1, "km": 1000, "cm": 0.01, "mm": 0.001, "mi": 1609.344, "yd": 0.9144, "ft": 0.3048, "in": 0.0254},
    "mass": {"kg": 1, "g": 0.001, "mg": 1e-6, "lb": 0.45359237, "oz": 0.028349523, "t": 1000, "st": 6.35029318},
    "volume": {"l": 1, "ml": 0.001, "gal": 3.785411784, "cup": 0.24, "floz": 0.0295735, "tbsp": 0.0147868,
               "tsp": 0.00492892},
    "speed": {"kmh": 1, "mph": 1.609344, "ms": 3.6, "knot": 1.852},
    "time": {"s": 1, "min": 60, "h": 3600, "day": 86400, "week": 604800, "year": 31557600},
    "data": {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12},
    "area": {"m2": 1, "km2": 1e6, "ft2": 0.09290304, "acre": 4046.8564224, "hectare": 1e4, "sqyd": 0.83612736},
}
_ALIASES = {
    "meter": "m", "metre": "m", "meters": "m", "metres": "m", "kilometer": "km", "kilometre": "km", "kilometers": "km",
    "kilometres": "km", "centimeter": "cm", "centimeters": "cm", "centimetre": "cm", "millimeter": "mm",
    "millimeters": "mm", "mile": "mi", "miles": "mi", "yard": "yd", "yards": "yd", "foot": "ft", "feet": "ft",
    "inch": "in", "inches": "in",
    "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kilos": "kg", "kgs": "kg", "gram": "g", "grams": "g",
    "milligram": "mg", "milligrams": "mg", "pound": "lb", "pounds": "lb", "lbs": "lb", "ounce": "oz", "ounces": "oz",
    "ton": "t", "tons": "t", "tonne": "t", "tonnes": "t", "stone": "st", "stones": "st",
    "liter": "l", "litre": "l", "liters": "l", "litres": "l", "milliliter": "ml", "millilitre": "ml",
    "milliliters": "ml", "gallon": "gal", "gallons": "gal", "cups": "cup", "fluid ounce": "floz",
    "fluid ounces": "floz", "tablespoon": "tbsp", "tablespoons": "tbsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "km/h": "kmh", "kph": "kmh", "kilometers per hour": "kmh", "kilometres per hour": "kmh",
    "miles per hour": "mph", "m/s": "ms", "meters per second": "ms", "knots": "knot",
    "second": "s", "seconds": "s", "sec": "s", "minute": "min", "minutes": "min", "mins": "min", "hour": "h",
    "hours": "h", "hr": "h", "days": "day", "weeks": "week", "years": "year",
    "byte": "b", "bytes": "b", "kilobyte": "kb", "kilobytes": "kb", "megabyte": "mb", "megabytes": "mb",
    "gigabyte": "gb", "gigabytes": "gb", "terabyte": "tb", "terabytes": "tb",
    "square meter": "m2", "square meters": "m2", "square metres": "m2", "square kilometers": "km2",
    "square feet": "ft2", "square foot": "ft2", "sq ft": "ft2", "acres": "acre", "hectares": "hectare",
    "square yards": "sqyd",
    "c": "celsius", "°c": "celsius", "centigrade": "celsius", "degrees celsius": "celsius",
    "f": "fahrenheit", "°f": "fahrenheit", "degrees fahrenheit": "fahrenheit", "k": "kelvin", "kelvins": "kelvin",
}
_TEMPS = {"celsius", "fahrenheit", "kelvin"}


def _unit(u: str) -> str:
    u = u.strip().lower().rstrip(".")
    return _ALIASES.get(u, u)


def _temp(v, a, b):
    c = v if a == "celsius" else (v - 32) * 5 / 9 if a == "fahrenheit" else v - 273.15
    return c if b == "celsius" else c * 9 / 5 + 32 if b == "fahrenheit" else c + 273.15


def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    a, b = _unit(from_unit), _unit(to_unit)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "Which number should I convert?"
    if a in _TEMPS and b in _TEMPS:
        return f"{fmt(v)} {a} is {fmt(round(_temp(v, a, b), 1))} {b}."
    for table in _UNITS.values():
        if a in table and b in table:
            return f"{fmt(v)} {from_unit.strip()} is {fmt(v * table[a] / table[b])} {to_unit.strip()}."
    return f"I can't convert {from_unit} to {to_unit}."

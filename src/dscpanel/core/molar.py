"""Molar masses from what a chemist types: a sum formula, a SMILES, or a
composition of building blocks.

A small calculator beside the molar mass. Three readings:

* **a sum formula**: element symbols and counts, brackets with a count
  after them, decimals, and adducts after `*` (or the
  middle dot; a "." is a decimal point): `C6H6`, `Zn(C3H3N2)2`,
  `C14.2H12.6N4O2Zn`, `CuSO4*5H2O`;
* **a SMILES**: hydrogens added, as RDKit counts them: `O=C(O)c1ccccc1`;
* **a composition**: components `(key)coefficient` or `key[coefficient]`,
  joined by `+` or nothing, where a key is a building block of
  `BUILDING_BLOCKS` - or any sum formula or SMILES written in the
  brackets: `Zn(im)1.70(bim)0.30`.

`calculate(text)` reads it the way that fits (`read` says which) or the
way asked for. The atomic weights are RDKit's. RDKit is a dependency;
without it the calculator says so rather than guessing.

UI-free.
"""

import re
from collections import OrderedDict

#: The building blocks of a composition: a key, as it is typed, and its
#: SMILES.
BUILDING_BLOCKS = OrderedDict((
    ("im", "C1=NC=C[N-]1"),
    ("imH", "C1=NC=CN1"),
    ("Clim", "ClC1=C[N-]C=N1"),
    ("Brim", "BrC1=C[N-]C=N1"),
    ("Iim", "IC1=C[N-]C=N1"),
    ("Fim", "FC1=C[N-]C=N1"),
    ("dClim", "ClC1=C(Cl)[N-]C=N1"),
    ("mim", "CC1=C[N-]C=N1"),
    ("mimH", "CC1=CNC=N1"),
    ("mbim", "CC1=CC=C2C(N=C[N-]2)=C1"),
    ("CNim", "N#CC1=C[N-]C=N1"),
    ("dCNim", "N#CC1=C(C#N)N=C[N-]1"),
    ("bim", "C12=CC=CC=C1[N-]C=N2"),
    ("Zn", "[Zn++]"),
    ("Co", "[Co++]"),
    ("bc", "C1=CC=CC=C1C(=O)[O-]"),
    ("Hbc", "C1=CC=CC=C1C(=O)O"),
    ("H2bdc", "O=C(O)C1=CC=C(C(O)=O)C=C1"),
    ("bdc", "O=C([O-])C1=CC=C(C([O-])=O)C=C1"),
    ("Hpc", "O=C(O)C1=NC=CC=C1"),
    ("pc", "O=C([O-])C1=NC=CC=C1"),
    ("H2pPDA", "O=C(O)CC1=CC=C(CC(O)=O)C=C1"),
    ("HoPyBz", "O=C(O)C(C=C1)=CC=C1C2=CC=CN=C2"),
    ("HpPyBz", "O=C(O)C(C=C1)=CC=C1C2=CC=NC=C2"),
    ("H2adp", "OC(CCCCC(O)=O)=O"),
))

AUTO = "auto"
FORMULA = "formula"
SMILES = "smiles"
COMPOSITION = "composition"
READINGS = (AUTO, FORMULA, SMILES, COMPOSITION)
TITLES = {AUTO: "whichever fits", FORMULA: "a sum formula",
          SMILES: "a SMILES", COMPOSITION: "a composition"}


class Result(object):
    """What `calculate` found: how it read the text, the atom counts
    (symbol -> count, possibly fractional), the Hill formula, the molar mass
    in g/mol - or `error` and no mass."""

    def __init__(self, read=None, counts=None, error=None):
        self.read = read
        self.counts = dict(counts or {})
        self.error = error
        self.mass = None
        self.formula = ""
        if counts and error is None:
            try:
                self.mass = mass_of(self.counts)
                self.formula = hill(self.counts)
            except ValueError as exc:
                self.error = str(exc)

    @property
    def ok(self):
        return self.error is None and self.mass is not None


def _table():
    from rdkit import Chem
    return Chem.GetPeriodicTable()


def available():
    try:
        _table()
    except ImportError:
        return False
    return True


_SYMBOLS = []


def _is_element(symbol):
    """True for an element symbol - looked up in a set made once, since
    RDKit asked about a key such as "bim" prints a C++ complaint to the
    console."""
    if not _SYMBOLS:
        table = _table()
        _SYMBOLS.append(frozenset(table.GetElementSymbol(z)
                                  for z in range(1, 119)))
    return symbol in _SYMBOLS[0]


def mass_of(counts):
    """g/mol of `counts` (symbol -> count), RDKit's atomic weights."""
    table = _table()
    total = 0.0
    for symbol, count in counts.items():
        if not _is_element(symbol):
            raise ValueError("{} is not an element".format(symbol))
        total += table.GetAtomicWeight(symbol) * float(count)
    return total


def hill(counts, decimals=3):
    """The Hill formula: C, then H, then the rest alphabetically (all
    alphabetically without carbon); fractional counts to `decimals`."""
    def written(count):
        count = round(float(count), decimals)
        if count == int(count):
            count = int(count)
        return "" if count == 1 else "%g" % count

    present = dict((s, c) for s, c in counts.items() if abs(c) > 1e-12)
    if "C" in present:
        order = ["C"] + (["H"] if "H" in present else [])
        order += sorted(s for s in present if s not in ("C", "H"))
    else:
        order = sorted(present)
    return "".join(s + written(present[s]) for s in order)


# ---------------------------------------------------------- sum formulas
_NUMBER = r"(?:\d+\.\d*|\.\d+|\d+)"
_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)(" + _NUMBER + r")?"
                            r"|([(\[])|([)\]])(" + _NUMBER + r")?")
_ADDUCT = re.compile(r"[*\u00b7]")


def parse_formula(text):
    """A sum formula as `{symbol: count}`, or ValueError. Brackets carry
    a count after them; `*` or a middle dot starts an adduct with its own
    leading count (`CuSO4*5H2O`). A "." is a decimal point, never an
    adduct: `C14.2H12.6N4O2Zn`, a composition's fractional formula."""
    text = str(text or "").strip().replace(" ", "")
    if not text:
        raise ValueError("nothing to read")
    total = {}
    for part in _ADDUCT.split(text):
        if not part:
            raise ValueError("an empty part after a dot")
        lead = re.match(_NUMBER, part)
        factor = 1.0
        if lead and lead.end() < len(part):
            factor = float(lead.group(0))
            part = part[lead.end():]
        for symbol, count in _formula_part(part).items():
            total[symbol] = total.get(symbol, 0.0) + count * factor
    return total


def _formula_part(text):
    stack = [{}]
    pos = 0
    for match in _FORMULA_TOKEN.finditer(text):
        if match.start() != pos:
            raise ValueError("cannot read {!r}".format(text[pos:]))
        pos = match.end()
        symbol, count, opening, closing, times = match.groups()
        if symbol:
            if not _is_element(symbol):
                raise ValueError("{} is not an element".format(symbol))
            group = stack[-1]
            group[symbol] = group.get(symbol, 0.0) + (
                float(count) if count else 1.0)
        elif opening:
            stack.append({})
        else:
            if len(stack) < 2:
                raise ValueError("a bracket closed that was never opened")
            inner = stack.pop()
            factor = float(times) if times else 1.0
            outer = stack[-1]
            for key, value in inner.items():
                outer[key] = outer.get(key, 0.0) + value * factor
    if pos != len(text):
        raise ValueError("cannot read {!r}".format(text[pos:]))
    if len(stack) != 1:
        raise ValueError("a bracket is not closed")
    if not stack[0]:
        raise ValueError("no elements")
    return stack[0]


def _repeats_bare(text):
    """True when an element follows itself with no count between ("CC"):
    nobody writes a sum formula like that, so such text is a SMILES."""
    symbols = re.findall(r"[A-Z][a-z]?\d*", text)
    return any(a == b and not re.search(r"\d", a)
               for a, b in zip(symbols, symbols[1:]))


# ---------------------------------------------------------------- SMILES
def smiles_counts(text):
    """A SMILES's atoms, hydrogens included, as `{symbol: count}`."""
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    mol = Chem.MolFromSmiles(str(text or "").strip())
    if mol is None:
        raise ValueError("not a SMILES")
    counts = {}
    for atom in Chem.AddHs(mol).GetAtoms():
        symbol = atom.GetSymbol()
        counts[symbol] = counts.get(symbol, 0.0) + 1.0
    return counts


# ----------------------------------------------------------- compositions
# His grammar, word for word (`_TOKEN_RE` in calculate_sum_formula.py).
_COEF = r"\d*\.\d+|\d+"
_COMPONENT = re.compile(
    r"\((?P<pkey>[^()]+)\)\s*(?P<pcoef>%s)?"
    r"|(?P<bkey>[A-Za-z]+)\s*(?P<bcoef>%s)?"
    r"|(?P<sep>[+\u00b7*\s])" % (_COEF, _COEF))


def parse_composition(text):
    """`[(key, coefficient), ...]`, or ValueError."""
    text = str(text or "").strip()
    found = []
    pos = 0
    for match in _COMPONENT.finditer(text):
        if match.start() != pos:
            raise ValueError("cannot read {!r}".format(text[pos:match.start()]))
        pos = match.end()
        if match.group("sep") is not None:
            continue
        if match.group("pkey") is not None:
            key, coef = match.group("pkey").strip(), match.group("pcoef")
        else:
            key, coef = match.group("bkey"), match.group("bcoef")
        found.append((key, float(coef) if coef is not None else 1.0))
    if pos != len(text):
        raise ValueError("cannot read {!r}".format(text[pos:]))
    if not found:
        raise ValueError("no components")
    return found


def component_counts(key, blocks=None):
    """One component's atoms: a building block, else a sum formula, else
    a SMILES written in the brackets."""
    blocks = BUILDING_BLOCKS if blocks is None else blocks
    if key in blocks:
        return smiles_counts(blocks[key])
    try:
        return parse_formula(key)
    except ValueError:
        pass
    try:
        return smiles_counts(key)
    except ValueError:
        raise ValueError("{} is no building block, formula or SMILES"
                         .format(key))


def composition_counts(text, blocks=None):
    total = {}
    for key, coef in parse_composition(text):
        for symbol, count in component_counts(key, blocks).items():
            total[symbol] = total.get(symbol, 0.0) + count * coef
    return total


def _uses_blocks(text, blocks):
    """True when a composition names a building block that is not simply
    an element too (Zn and Co are both: "ZnO" is a sum formula)."""
    try:
        return any(key in blocks and not _is_element(key)
                   for key, _c in parse_composition(text))
    except ValueError:
        return False


# ------------------------------------------------------------ calculating
def calculate(text, reading=AUTO, blocks=None):
    """`text` as a `Result`: read as asked, or - AUTO - as the first that
    fits of a composition with a known building block, a sum formula (not
    one with an element twice in a row, "CC", which is a SMILES), a SMILES,
    and a composition of formulas and SMILES."""
    text = str(text or "").strip()
    blocks = BUILDING_BLOCKS if blocks is None else blocks
    if not text:
        return Result(error="Type a formula, a SMILES or a composition.")
    if not available():
        return Result(error="RDKit is not installed: pip install rdkit")
    tries = {
        FORMULA: lambda: parse_formula(text),
        SMILES: lambda: smiles_counts(text),
        COMPOSITION: lambda: composition_counts(text, blocks),
    }
    if reading != AUTO:
        try:
            return Result(reading, tries[reading]())
        except ValueError as exc:
            return Result(reading, error="Not {}: {}".format(
                TITLES[reading], exc))
    errors = []
    if _uses_blocks(text, blocks):
        try:
            return Result(COMPOSITION, tries[COMPOSITION]())
        except ValueError as exc:
            errors.append(str(exc))
    # A formula and a SMILES may both read ("CO", "CCO"): then an element
    # twice in a row with no count ("CC") says SMILES, else the formula.
    found = {}
    for kind in (FORMULA, SMILES):
        try:
            found[kind] = tries[kind]()
        except ValueError as exc:
            errors.append(str(exc))
    if FORMULA in found and SMILES in found:
        kind = SMILES if _repeats_bare(text) else FORMULA
        return Result(kind, found[kind])
    for kind in (FORMULA, SMILES):
        if kind in found:
            return Result(kind, found[kind])
    try:
        return Result(COMPOSITION, tries[COMPOSITION]())
    except ValueError as exc:
        errors.append(str(exc))
    return Result(error="Not a formula, a SMILES or a composition "
                        "({}).".format(errors[0] if errors else "?"))

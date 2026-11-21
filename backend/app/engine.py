"""서버가 배정·조율 함수를 가져오는 유일한 곳.

- 배정 함수 5개: backend/app/solver/ (패키지 자체 또는 그 안의 모듈)
- 조율 함수 4개: backend/app/nlp/coord.py
같은 이름의 진짜 함수가 있으면 그걸 쓰고, 없으면(ImportError 또는 이름 없음) stubs.py의 가짜를 쓴다.
함수마다 따로 판단하므로 하나씩 진짜로 바꿔 끼워도 된다.

main.py와 store.py는 stubs.py를 직접 import하지 않고 이 파일만 쓴다.
"""

import importlib
import pkgutil
from typing import Callable, Dict, List, Optional, Tuple

from . import stubs

ASSIGN_NAMES = ("check_rules", "make_draft", "make_alternatives", "reassign", "what_if")
COORD_NAMES = ("write_message", "check_message", "parse_reply", "match_conditions")

_PKG = __package__  # "backend.app"


def _import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _solver_modules() -> List[object]:
    """solver 패키지와 그 바로 아래 모듈들. 패키지가 없으면 빈 목록."""
    pkg = _import(f"{_PKG}.solver")
    if pkg is None:
        return []
    mods = [pkg]
    for info in pkgutil.iter_modules(getattr(pkg, "__path__", [])):
        mod = _import(f"{pkg.__name__}.{info.name}")
        if mod is not None:
            mods.append(mod)
    return mods


def _pick(name: str, modules: List[object]) -> Tuple[Callable, str]:
    for mod in modules:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn, f"real ({mod.__name__})"
    return getattr(stubs, name), "stub"


def _resolve() -> Dict[str, Tuple[Callable, str]]:
    solver_mods = _solver_modules()
    coord_mod: Optional[object] = _import(f"{_PKG}.nlp.coord")
    coord_mods = [coord_mod] if coord_mod is not None else []
    table = {n: _pick(n, solver_mods) for n in ASSIGN_NAMES}
    table.update({n: _pick(n, coord_mods) for n in COORD_NAMES})
    return table


_TABLE = _resolve()

check_rules = _TABLE["check_rules"][0]
make_draft = _TABLE["make_draft"][0]
make_alternatives = _TABLE["make_alternatives"][0]
reassign = _TABLE["reassign"][0]
what_if = _TABLE["what_if"][0]

write_message = _TABLE["write_message"][0]
check_message = _TABLE["check_message"][0]
parse_reply = _TABLE["parse_reply"][0]
match_conditions = _TABLE["match_conditions"][0]


def sources() -> Dict[str, str]:
    """함수 이름 → "stub" 또는 "real (모듈 이름)"."""
    return {name: src for name, (_, src) in _TABLE.items()}

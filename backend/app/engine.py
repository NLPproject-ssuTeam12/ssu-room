"""서버가 배정·조율 함수를 가져오는 유일한 곳.

- 배정 함수 5개: backend/app/solver/ (패키지 자체 또는 그 안의 모듈)
- 조율 함수 4개: backend/app/nlp/coord.py
같은 이름의 진짜 함수가 있으면 그걸 쓰고, 없으면 stubs.py의 가짜를 쓴다.
함수마다 따로 판단하므로 하나씩 진짜로 바꿔 끼워도 된다.

- 모듈 자체가 없음                → 경고 없이 가짜
- 모듈은 있는데 불러오다 실패      → 가짜를 쓰되 경고 (load_warnings, 서버 시작 로그)
  (문법 오류, 모듈 안에서 필요한 패키지가 없어 나는 ImportError 등 모든 에러)
- 모듈은 불러왔는데 그 이름이 없음 → 경고 없이 가짜

main.py와 store.py는 stubs.py를 직접 import하지 않고 이 파일만 쓴다.
"""

import importlib
import importlib.util
import pkgutil
import sys
from typing import Callable, Dict, List, Optional, Tuple

from . import stubs

ASSIGN_NAMES = ("check_rules", "make_draft", "make_alternatives", "reassign", "what_if")
COORD_NAMES = ("write_message", "check_message", "parse_reply", "match_conditions")

_PKG = __package__  # "backend.app"


def _exists(name: str) -> bool:
    if name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:   # 부모 패키지가 없음
        return False


def _load(name: str, failures: List[str]):
    """모듈이 없으면 None. 있는데 실패하면 None + failures에 이유를 남긴다."""
    if not _exists(name):
        return None
    try:
        return importlib.import_module(name)
    except Exception as e:  # noqa: BLE001 - 어떤 에러든 서버는 떠야 한다
        failures.append(f"{name}: {type(e).__name__}: {e}")
        return None


def _solver_modules(failures: List[str]) -> List[object]:
    """solver 패키지와 그 바로 아래 모듈들. 패키지가 없으면 빈 목록."""
    pkg = _load(f"{_PKG}.solver", failures)
    if pkg is None:
        return []
    mods = [pkg]
    for info in pkgutil.iter_modules(getattr(pkg, "__path__", [])):
        mod = _load(f"{pkg.__name__}.{info.name}", failures)
        if mod is not None:
            mods.append(mod)
    return mods


def _pick(name: str, modules: List[object]) -> Tuple[Callable, str]:
    for mod in modules:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn, f"real ({mod.__name__})"
    return getattr(stubs, name), "stub"


def _resolve() -> Tuple[Dict[str, Tuple[Callable, str]], List[str]]:
    table: Dict[str, Tuple[Callable, str]] = {}
    warnings: List[str] = []

    groups = []
    solver_fail: List[str] = []
    groups.append((ASSIGN_NAMES, _solver_modules(solver_fail), solver_fail))
    coord_fail: List[str] = []
    coord_mod: Optional[object] = _load(f"{_PKG}.nlp.coord", coord_fail)
    groups.append((COORD_NAMES, [coord_mod] if coord_mod is not None else [], coord_fail))

    for names, mods, fails in groups:
        for n in names:
            table[n] = _pick(n, mods)
            if table[n][1] == "stub" and fails:
                warnings.append(f"{n} 함수: 진짜 모듈 불러오기 실패 → 가짜 사용 ({'; '.join(fails)})")
    return table, warnings


_TABLE, _WARNINGS = _resolve()

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


def load_warnings() -> List[str]:
    """진짜 모듈이 있는데 불러오지 못해 가짜를 쓰는 함수 목록 (이유 포함)."""
    return list(_WARNINGS)

"""테스트 경로 설정. 저장소 맨 위와 backend/ 안 어디서 pytest를 돌려도 `backend.app`을 찾게 한다.

(backend/ 안에서 돌리면 저장소 맨 위가 import 경로에 없어 'No module named backend'가 났다.)
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

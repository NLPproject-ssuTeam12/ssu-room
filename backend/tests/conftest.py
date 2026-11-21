"""테스트 공용 설정.

starlette 0.21(fastapi 0.87)의 TestClient는 anyio 3의 anyio.start_blocking_portal을 부른다.
anyio 4에서는 anyio.from_thread.start_blocking_portal로 옮겨져서, 없으면 이어 준다.
(서버 실행에는 영향 없음. 테스트에서만 쓴다.)
"""

import anyio
import anyio.from_thread

if not hasattr(anyio, "start_blocking_portal"):
    anyio.start_blocking_portal = anyio.from_thread.start_blocking_portal

"""서버 실행기.  python serve.py  [--reload]

환경 변수: AXREVIEW_PORT(기본 5002) · AXREVIEW_HOST(기본 127.0.0.1) · AXREVIEW_SCHEDULER=1(배치 실행, start-public 이 설정)
"""
import os
import sys

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("AXREVIEW_PORT", "5002"))
    host = os.environ.get("AXREVIEW_HOST", "127.0.0.1")
    uvicorn.run("api.main:app", host=host, port=port, reload="--reload" in sys.argv, workers=1, proxy_headers=False,
                log_level="info", access_log=False)

@echo off
chcp 65001 >nul
rem 개발 실행 — 백엔드(5002, 코드 바뀌면 자동 재시작) + 프론트 개발 서버(5173, /api 는 5002 로 프록시)
cd /d "%~dp0"
start "AX Review API (5002)" cmd /k "cd backend && set AXREVIEW_PORT=5002&& venv\Scripts\python serve.py --reload"
start "AX Review Front (5173)" cmd /k "cd frontend && npm run dev"
echo 백엔드 http://localhost:5002  ·  화면 http://localhost:5173  (로컬 접속은 관리자)

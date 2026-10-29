"""API 라우터 모음 — 이 패키지의 각 모듈이 `router = APIRouter(...)`를 내보내면 main.py가 자동으로 등록한다.

공개: site, me, home, notes, today, lab, play(type·terms·diagnosis), ask, subscribe(구독·확인·해지·추천·문의·월 구독), privacy, letter
관리: admin_* (모두 deps.require_admin)
"""

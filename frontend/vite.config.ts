import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발: npm run dev (5173) → /api·/app/static·/n/·/s/·/r/ 는 백엔드(5002)로 프록시
// 배포: npm run build → dist/ 를 백엔드가 그대로 서빙 (backend/api/main.py)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5002",
      "/app/static": "http://127.0.0.1:5002",
      "/n/": "http://127.0.0.1:5002",
      "/s/": "http://127.0.0.1:5002",
      "/r/": "http://127.0.0.1:5002",
      "/sitemap.xml": "http://127.0.0.1:5002",
      "/robots.txt": "http://127.0.0.1:5002",
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});

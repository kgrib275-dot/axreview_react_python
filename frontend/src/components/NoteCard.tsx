// 노트 카드 — 목록·홈·추천에서 공용. ☆ 북마크는 브라우저(localStorage)에만 남는다.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

export type NoteCardData = {
  id: number; title: string; category: string; kind: string; summary: string; published: string; source?: string;
  tags?: string; audiences?: string; industries?: string[]; similarity?: number; views?: number;
};

const KEY = "axreview-bookmarks";
export function loadBookmarks(): Set<number> {
  try { return new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch { return new Set(); }
}
export function saveBookmarks(s: Set<number>) {
  try { localStorage.setItem(KEY, JSON.stringify([...s])); } catch { /* 사생활 보호 모드 */ }
}
export function useBookmarks(): [Set<number>, (id: number) => void] {
  const [bm, setBm] = useState<Set<number>>(() => loadBookmarks());
  useEffect(() => saveBookmarks(bm), [bm]);
  return [bm, (id) => setBm((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; })];
}

export default function NoteCard({ n, fresh, bookmarked, onBookmark }: { n: NoteCardData; fresh?: boolean; bookmarked?: boolean; onBookmark?: (id: number) => void }) {
  return (
    <Link to={`/notes?id=${n.id}`} className={`card ${fresh ? "fresh" : ""}`}>
      {onBookmark && (
        <button type="button" className={`ax-bm ${bookmarked ? "on" : ""}`} aria-label="북마크" title="북마크"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); onBookmark(n.id); }}>{bookmarked ? "★" : "☆"}</button>
      )}
      <div className="meta"><span className="chip">{n.category}</span><span>{n.kind}</span>{n.published && <span>· {n.published}</span>}</div>
      <h3>{n.title}</h3>
      <p>{n.summary}</p>
      {(n.industries?.length || n.similarity !== undefined) && (
        <div className="meta">
          {n.industries?.map((i) => <span key={i}>#{i}</span>)}
          {n.similarity !== undefined && <span>유사도 {n.similarity.toFixed(2)}</span>}
        </div>
      )}
    </Link>
  );
}

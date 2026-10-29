// 데일리 브리핑 — 날짜별 수집 현황(오늘은 실시간, 지난 날짜는 아카이브), 핵심 TOP 5, 소스·카테고리별 (app_pages/admin/briefing.py).
import { useState } from "react";
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, DataTable, Expander, Row, asArray, isObj, num, pick, str, today, useAct } from "./common";
import { StartJob, useJobs } from "./JobRunner";

const CATS = ["AX Strategy", "AX Implementation", "AX Enablement"];
const counts = (v: unknown): Record<string, number> => (isObj(v) ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, num(x)])) : {});

export default function Briefing() {
  const t = today();
  const [picked, setPicked] = useState(t);
  const { finished } = useJobs();
  const act = useAct();
  const dates = useLoad(async () => {
    const r = await A.get("briefing/dates");
    const list = asArray<string | Row>(r, "dates", "archived").map((x) => (isObj(x) ? str(pick(x, "date", "day")) : String(x)));
    const srvToday = isObj(r) ? str(r.today) : "";
    return { list, today: srvToday || t };
  }, []);
  const tday = dates.data?.today || t;
  const { data, error, reload } = useLoad(() => A.get<Row>(`briefing?date=${picked}`), [picked, finished]);
  const c = data && isObj(data.content) ? (data.content as Row) : data || {};
  const empty = !data || pick(c, "total_count", "count") === undefined;
  const srcCounts = counts(c.source_counts);
  const catCounts = counts(c.category_counts);
  const top = asArray(c.top_articles);
  const briefs = isObj(c.spotlight) ? (c.spotlight as Record<string, string>) : isObj(c.briefs) ? (c.briefs as Record<string, string>) : {};
  const catNews = isObj(c.category_news) ? (c.category_news as Record<string, unknown>) : {};
  const srcNews = isObj(c.source_top_news) ? (c.source_top_news as Record<string, unknown>) : {};
  const allDates = [tday, ...(dates.data?.list || []).filter((d) => d !== tday)];

  return (
    <div>
      <AdminHead title="데일리 브리핑" note="날짜별 수집 현황입니다. 지난 날짜는 다음 날 확정(아카이브)되어 이후 데이터가 바뀌어도 그대로 보입니다." />
      <div className="inline" style={{ marginBottom: 14 }}>
        <div className="field">
          <label>날짜</label>
          <select value={picked} onChange={(e) => setPicked(e.target.value)}>
            {allDates.map((d) => <option key={d} value={d}>{d === tday ? `${d} (오늘 · 실시간)` : `${d} (확정)`}</option>)}
          </select>
        </div>
        <div className="field narrow">
          <label>&nbsp;</label>
          <input type="date" value={picked} max={tday} onChange={(e) => e.target.value && setPicked(e.target.value)} />
        </div>
        <button
          className="btn"
          onClick={async () => {
            await act(() => A.post("briefing/archive", { date: picked }), `${picked} 를 확정(아카이브)했습니다.`);
            reload();
            dates.reload();
          }}
        >
          📦 이 날짜 확정(아카이브)
        </button>
      </div>
      {error && <Alert kind="err">{error}</Alert>}
      {!error && empty && data && <Alert kind="info">이 날짜에 수집된 기사가 없습니다.</Alert>}
      {!empty && (
        <div>
          <div className="metrics">
            <Metric k="수집 기사 (키워드 통과)" v={num(pick(c, "total_count", "count"))} />
            <Metric k="평균 AX 점수" v={str(c.avg_score) || "-"} />
            <Metric k="소스" v={Object.keys(srcCounts).length} />
            {CATS.map((cat) => <Metric key={cat} k={cat} v={catCounts[cat] || 0} />)}
          </div>
          {c.archived_at !== undefined && <p className="caption">확정 시각 {str(c.archived_at).replace("T", " ")}</p>}

          <h3>핵심 TOP 5</h3>
          {Object.keys(briefs).length > 0 && <p className="caption">상위 3건은 AI가 서로의 맥락을 함께 읽고 새로 쓴 브리핑입니다.</p>}
          {top.map((a, i) => {
            const url = str(a.url);
            const cats = Array.isArray(a.categories) ? a.categories.join(", ") : str(a.categories);
            const hash = str(pick(a, "url_hash", "hash"));
            return (
              <div key={url || i} className="box sm">
                <div className="title">{i + 1}. <a href={url} target="_blank" rel="noreferrer">{str(a.title)}</a></div>
                <div className="caption">{str(a.source)} · 점수 {num(a.score)} · {cats || "분류 없음"}</div>
                <p style={{ margin: "6px 0", fontSize: ".9rem" }}>{briefs[url] || str(a.summary)}</p>
                {a.status === "new" && hash && <StartJob kind="draft" text="📝 이 기사로 노트 초안 만들기" kwargs={{ hashes: [hash] }} />}
              </div>
            );
          })}

          <div className="row2" style={{ marginTop: 16 }}>
            <div>
              <h3>소스별 수집</h3>
              <DataTable rows={Object.entries(srcCounts).sort((a, b) => b[1] - a[1]).map(([s, n]) => ({ 소스: s, 건수: n }))} tall />
            </div>
            <div>
              <h3>카테고리별 주요 기사</h3>
              {Object.entries(catNews).map(([cat, items]) => (
                <Expander key={cat} title={`${cat} · ${catCounts[cat] ?? asArray(items).length}건`}>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: ".88rem" }}>
                    {asArray(items).map((a, i) => (
                      <li key={i}><a href={str(a.url)} target="_blank" rel="noreferrer">{str(a.title)}</a> · {str(a.source)} · {num(a.score)}점</li>
                    ))}
                  </ul>
                </Expander>
              ))}
            </div>
          </div>

          <h3 style={{ marginTop: 16 }}>소스별 주요 기사</h3>
          {Object.entries(srcNews).map(([src, items]) => (
            <Expander key={src} title={`${src} · ${srcCounts[src] ?? asArray(items).length}건`}>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: ".88rem" }}>
                {asArray(items).map((a, i) => (
                  <li key={i}>
                    <a href={str(a.url)} target="_blank" rel="noreferrer">{str(a.title)}</a> · {num(a.score)}점
                    <div className="caption">{str(a.summary).slice(0, 160)}</div>
                  </li>
                ))}
              </ul>
            </Expander>
          ))}
        </div>
      )}
    </div>
  );
}

// 주간 PDF 리포트 — 게시된 주간 흐름을 골라 PDF 를 만들고 내려받기/공개 링크·미리보기 (app_pages/admin/report.py).
import { useState } from "react";
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Row, asArray, isObj, num, pick, str, useAct } from "./common";
import { JobStatus, useJobs } from "./JobRunner";

export default function Report() {
  const { finished, isActive, refresh } = useJobs();
  const act = useAct();
  const { data, error, reload } = useLoad(() => A.get<unknown>("reports"), [finished]);
  const issues = asArray(data, "issues", "reports", "items");
  const [selId, setSelId] = useState<string>("");
  const issue = issues.find((i) => str(i.id) === selId) || issues[0];
  const info: Row = issue || {};
  const notes = Array.isArray(info.notes) ? info.notes.length : num(pick(info, "notes", "note_count"));
  const stats = isObj(info.stats) ? info.stats : info;
  const pdfUrl = str(pick(info, "pdf_url", "url", "public_url"));
  const exists = pdfUrl !== "" || !!pick(info, "exists", "has_pdf");
  const preview = str(pick(info, "preview_html", "html"));

  const make = async () => {
    await act(async () => { await A.post(`reports/${issue.id}`); }, "PDF 생성을 시작했습니다.");
    refresh();
    reload();
  };

  return (
    <div>
      <AdminHead title="주간 PDF 리포트" note="주간 흐름 + 그 주 노트(최대 10편) + 점검 질문으로 된 정사각 카드 리포트입니다. 만들면 홈의 '이번 주 AX 흐름'에 내려받기 버튼이 생기고, 메일·Teams에 링크가 붙습니다." />
      {error && <Alert kind="err">{error}</Alert>}
      {!issues.length && !error && <Alert kind="info">게시된 주간 흐름이 없습니다. '주간 흐름'에서 먼저 게시하세요.</Alert>}
      {issue && (
        <div>
          <div className="field">
            <label>대상 주간 흐름</label>
            <select value={str(issue.id)} onChange={(e) => setSelId(e.target.value)}>
              {issues.map((i) => <option key={str(i.id)} value={str(i.id)}>{`${str(i.week)} · ${str(i.headline_em)} ${str(i.headline)}`.slice(0, 90)}</option>)}
            </select>
          </div>
          <div className="metrics" style={{ alignItems: "flex-end" }}>
            <Metric k="노트" v={notes} />
            <Metric k="검토한 기사" v={num(pick(stats, "collected", "articles"))} />
            <Metric k="소스" v={num(stats.sources)} />
            <button className="btn primary" disabled={!notes || isActive("report")} onClick={make}>📄 {exists ? "PDF 다시 만들기" : "PDF 만들기"}</button>
          </div>
          <JobStatus only={["report"]} />
          {exists && pdfUrl && (
            <div className="btn-row" style={{ margin: "10px 0" }}>
              <a className="btn" href={pdfUrl} target="_blank" rel="noreferrer">⬇ PDF 열기 / 내려받기</a>
              <span className="caption">공개 링크: <a href={pdfUrl} target="_blank" rel="noreferrer">{pdfUrl}</a></span>
            </div>
          )}
          {!notes && <Alert kind="warn">이 주에 게시된 노트가 없어 리포트를 만들 수 없습니다.</Alert>}
          {notes > 0 && Array.isArray(info.notes) && (
            <ul style={{ fontSize: ".88rem" }}>{(info.notes as Row[]).map((n, i) => <li key={i}>{str(n.title)} <span className="caption">{str(n.category)}</span></li>)}</ul>
          )}
          {preview && (
            <div>
              <h3>미리보기</h3>
              <iframe className="adm-frame" title="리포트 미리보기" srcDoc={preview} style={{ height: 760 }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

"use client";

import initSqlJs from "sql.js";
import { useEffect, useState } from "react";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
type Proposal = { file_name: string; public_path: string };
type PlanSection = { id: string; title: string; page_start: number; page_end: number; summary: string; topics: string[] };
type PlanAnalysis = { candidate_id: string; sha256: string; method: string; summary: string; sections: PlanSection[] };
type PlanTopic = { id: string; label: string };
type Candidate = { tse_candidate_id: string; state_code: string; office: string; full_name: string; ballot_name: string; party_code: string; proposals: Proposal[]; analyses: PlanAnalysis[]; topicLabels: Record<string, string> };

export default function ProposalPage() {
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let closeDatabase: (() => void) | undefined;
    async function loadCandidate() {
      try {
        const candidateId = new URLSearchParams(window.location.search).get("candidate_id") ?? "";
        if (!/^\d+$/.test(candidateId)) { setLoaded(true); return; }
        const SQL = await initSqlJs({ locateFile: () => `${BASE_PATH}/vendor/sql-wasm.wasm` });
        const response = await fetch(`${BASE_PATH}/data/voto_em_pauta.sqlite3`);
        if (!response.ok) throw new Error("O snapshot de candidaturas ainda não foi publicado.");
        const database = new SQL.Database(new Uint8Array(await response.arrayBuffer()));
        closeDatabase = () => database.close();
        const candidateRows = database.exec("SELECT tse_candidate_id,state_code,office,full_name,ballot_name,party_code FROM candidates WHERE tse_candidate_id = ?", [candidateId])[0]?.values ?? [];
        if (!candidateRows.length) { setLoaded(true); return; }
        const proposalRows = database.exec("SELECT file_name,public_path FROM proposals WHERE candidate_id = ? ORDER BY file_name", [candidateId])[0]?.values ?? [];
        const analysisResponse = await fetch(`${BASE_PATH}/data/plan-analysis.json`);
        const analysisData = analysisResponse.ok ? await analysisResponse.json() as { documents?: PlanAnalysis[]; topics?: PlanTopic[] } : {};
        const row = candidateRows[0];
        const text = (value: unknown) => String(value ?? "");
        if (!cancelled) setCandidate({
          tse_candidate_id: text(row[0]), state_code: text(row[1]), office: text(row[2]), full_name: text(row[3]),
          ballot_name: text(row[4]), party_code: text(row[5]),
          proposals: proposalRows.map((item) => ({ file_name: text(item[0]), public_path: text(item[1]) })),
          analyses: (analysisData.documents ?? []).filter((item) => item.candidate_id === candidateId),
          topicLabels: Object.fromEntries((analysisData.topics ?? []).map((topic) => [topic.id, topic.label])),
        });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Não foi possível carregar os dados.");
      } finally {
        closeDatabase?.();
        if (!cancelled) setLoaded(true);
      }
    }
    void loadCandidate();
    return () => { cancelled = true; closeDatabase?.(); };
  }, []);

  return <main className="site-shell proposal-page">
    <header className="topbar"><a className="brand" href={`${BASE_PATH}/`}><span className="brand-mark" aria-hidden="true">VP</span><span>Voto em pauta</span></a><div className="topbar-meta"><span className="live-dot" /> ELEIÇÕES GERAIS <strong>2026</strong></div><a className="back-link" href={`${BASE_PATH}/`}>← Voltar às candidaturas</a></header>
    {candidate ? <>
      <section className="proposal-hero"><p className="eyebrow">PROPOSTAS REGISTRADAS NO TSE <span>·</span> {candidate.state_code}</p><h1>{candidate.ballot_name || candidate.full_name}</h1><p className="proposal-person">{candidate.full_name} <span>·</span> {candidate.office} <span>·</span> {candidate.party_code}</p></section>
      <section className="proposal-content">
        <div className="proposal-section-title"><div><p className="eyebrow">DOCUMENTOS ORIGINAIS</p><h2>Plano de governo</h2></div><span>{candidate.proposals.length} {candidate.proposals.length === 1 ? "arquivo" : "arquivos"}</span></div>
        {candidate.proposals.length ? <div className="document-list">{candidate.proposals.map((proposal, index) => <a className="document-row" key={proposal.file_name} href={`${BASE_PATH}${proposal.public_path}`} target="_blank" rel="noreferrer"><span className="document-number">{String(index + 1).padStart(2, "0")}</span><span className="document-file"><strong>Proposta de governo</strong><small>{proposal.file_name}</small></span><span className="document-format">PDF</span><span className="document-open" aria-label="Abrir arquivo">↗</span></a>)}</div> : <div className="empty-state"><h3>Documento não localizado</h3><p>Não encontramos uma proposta associada a esta candidatura nos dados publicados.</p></div>}
        {candidate.analyses.map((analysis) => <section className="plan-analysis" key={analysis.sha256}>
          <div className="analysis-heading"><div><p className="eyebrow">LEITURA ESTRUTURADA</p><h2>Resumo do plano</h2></div><span>{analysis.method.startsWith("extractive-") ? "RESUMO EXTRATIVO" : analysis.method === "text-extraction-unavailable" ? "TEXTO NÃO EXTRAÍVEL" : "RESUMO ASSISTIDO POR IA · PRÉ-COMPUTADO"}</span></div>
          <p className="analysis-summary">{analysis.summary}</p>
          <div className="analysis-sections">{analysis.sections.map((section) => <article className="analysis-section" key={section.id}>
            <div className="analysis-section-heading"><h3>{section.title}</h3><span>{section.page_start === section.page_end ? `P. ${section.page_start}` : `P. ${section.page_start}–${section.page_end}`}</span></div>
            <p>{section.summary}</p>
            <div className="topic-list">{section.topics.map((topic) => <span className="topic-tag" key={topic}>{candidate.topicLabels[topic] ?? topic}</span>)}</div>
          </article>)}</div>
          <p className="analysis-disclaimer">Resumo pré-computado a partir do texto extraído do PDF; não substitui a proposta original. Os tópicos seguem uma taxonomia fixa e podem não representar todas as nuances do documento.</p>
        </section>)}
        <p className="source-note">Documento oficial apresentado à Justiça Eleitoral. Fonte: TSE, Dados Abertos, CC BY. <a href="https://dadosabertos.tse.jus.br/dataset/candidatos-2026" target="_blank" rel="noreferrer">Consultar fonte ↗</a></p>
      </section>
    </> : <section className="proposal-content"><div className="empty-state"><h3>{error || (loaded ? "Candidatura não encontrada" : "Carregando proposta")}</h3><p>{error ? "Tente novamente mais tarde." : "Consulte a candidatura e os documentos oficiais do TSE."}</p><a href={`${BASE_PATH}/`}>Voltar às candidaturas</a></div></section>}
    <footer className="site-footer"><span>VOTO EM PAUTA <b>·</b> INFORMAÇÃO PARA ESCOLHER</span><span>Fonte: Tribunal Superior Eleitoral</span></footer>
  </main>;
}
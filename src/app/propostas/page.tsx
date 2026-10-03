"use client";

import initSqlJs from "sql.js";
import { useEffect, useState } from "react";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
type Proposal = { file_name: string; public_path: string };
type Candidate = { state_code: string; office: string; full_name: string; ballot_name: string; party_code: string; proposals: Proposal[] };

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
        const row = candidateRows[0];
        const text = (value: unknown) => String(value ?? "");
        if (!cancelled) setCandidate({
          state_code: text(row[1]), office: text(row[2]), full_name: text(row[3]),
          ballot_name: text(row[4]), party_code: text(row[5]),
          proposals: proposalRows.map((item) => ({ file_name: text(item[0]), public_path: text(item[1]) })),
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
        <p className="source-note">Documento oficial apresentado à Justiça Eleitoral. Fonte: TSE, Dados Abertos, CC BY. <a href="https://dadosabertos.tse.jus.br/dataset/candidatos-2026" target="_blank" rel="noreferrer">Consultar fonte ↗</a></p>
      </section>
    </> : <section className="proposal-content"><div className="empty-state"><h3>{error || (loaded ? "Candidatura não encontrada" : "Carregando proposta")}</h3><p>{error ? "Tente novamente mais tarde." : "Consulte a candidatura e os documentos oficiais do TSE."}</p><a href={`${BASE_PATH}/`}>Voltar às candidaturas</a></div></section>}
    <footer className="site-footer"><span>VOTO EM PAUTA <b>·</b> INFORMAÇÃO PARA ESCOLHER</span><span>Fonte: Tribunal Superior Eleitoral</span></footer>
  </main>;
}
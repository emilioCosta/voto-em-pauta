"use client";

import initSqlJs from "sql.js";
import { useEffect, useState } from "react";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
type Proposal = { file_name: string; public_path: string };
type PlanExcerpt = { id: string; page_start: number; page_end: number; text: string };
type PlanSection = { id: string; title: string; page_start: number | null; page_end: number | null; summary: string; topics: string[]; excerpts: PlanExcerpt[] };
type PlanAnalysis = { candidate_id: string; sha256: string; method: string; summary: string; sections: PlanSection[] };
type PlanTopic = { id: string; label: string };
type SenatorStatement = { text: string; section_title: string; topics: string[]; source_url: string; source_title: string; source_sha256: string; collected_at: string };
type SenatorTopicSection = { id: string; label: string; summary: string; excerpts: SenatorStatement[] };
type SenatorProposalData = { candidate_id: string; status: string; declared_sites: string[]; sources: Array<{ url: string; title: string; collected_at: string; kind: string }>; statements: SenatorStatement[]; sections: SenatorTopicSection[] };
type Candidate = { tse_candidate_id: string; state_code: string; office: string; full_name: string; ballot_name: string; party_code: string; proposals: Proposal[]; analyses: PlanAnalysis[]; topicLabels: Record<string, string>; senatorProposal?: SenatorProposalData };

function analysisCategory(office: string) {
  const exactCategories: Record<string, string> = {
    PRESIDENTE: "presidente",
    "VICE-PRESIDENTE": "vice-presidente",
    GOVERNADOR: "governador",
    "VICE-GOVERNADOR": "vice-governador",
    SENADOR: "senador",
    "1º SUPLENTE": "senador",
    "2º SUPLENTE": "senador",
  };
  if (exactCategories[office]) return exactCategories[office];
  if (office.startsWith("DEPUTADO ")) return "deputado";
  return office.toLocaleLowerCase("pt-BR").normalize("NFD").replace(/\p{Diacritic}/gu, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "outros";
}

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
        const row = candidateRows[0];
        const text = (value: unknown) => String(value ?? "");
        const proposalRows = database.exec("SELECT file_name,public_path FROM proposals WHERE candidate_id = ? ORDER BY file_name", [candidateId])[0]?.values ?? [];
        const analysisPath = `${BASE_PATH}/data/plan-analysis/${analysisCategory(text(row[2]))}/${encodeURIComponent(text(row[1]))}.json`;
        const analysisResponse = proposalRows.length ? await fetch(analysisPath) : null;
        const analysisData = analysisResponse?.ok ? await analysisResponse.json() as { documents?: PlanAnalysis[]; topics?: PlanTopic[] } : {};
        const isSenator = text(row[2]) === "SENADOR";
        const senatorResponse = isSenator ? await fetch(`${BASE_PATH}/data/senator-proposals/${encodeURIComponent(text(row[1]))}.json`) : null;
        const senatorData = senatorResponse?.ok ? await senatorResponse.json() as { candidates?: SenatorProposalData[]; topics?: PlanTopic[] } : {};
        const senatorProposal = senatorData.candidates?.find((item) => item.candidate_id === candidateId);
        if (!cancelled) setCandidate({
          tse_candidate_id: text(row[0]), state_code: text(row[1]), office: text(row[2]), full_name: text(row[3]),
          ballot_name: text(row[4]), party_code: text(row[5]),
          proposals: proposalRows.map((item) => ({ file_name: text(item[0]), public_path: text(item[1]) })),
          analyses: (analysisData.documents ?? []).filter((item) => item.candidate_id === candidateId),
          topicLabels: Object.fromEntries([...(analysisData.topics ?? []), ...(senatorData.topics ?? [])].map((topic) => [topic.id, topic.label])),
          senatorProposal,
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

  const isLegislativeCandidate = candidate?.office.startsWith("DEPUTADO ") || candidate?.office === "SENADOR";

  return <main className="site-shell proposal-page">
    <header className="topbar"><a className="brand" href={`${BASE_PATH}/`}><span className="brand-mark" aria-hidden="true">VP</span><span>Voto em pauta</span></a><div className="topbar-meta"><span className="live-dot" /> ELEIÇÕES GERAIS <strong>2026</strong></div><a className="back-link" href={`${BASE_PATH}/`}>← Voltar às candidaturas</a></header>
    {candidate ? <>
      <section className="proposal-hero"><p className="eyebrow">{candidate.office === "SENADOR" ? "CANDIDATURA AO SENADO" : "PROPOSTAS REGISTRADAS NO TSE"} <span>·</span> {candidate.state_code}</p><h1>{candidate.ballot_name || candidate.full_name}</h1><p className="proposal-person">{candidate.full_name} <span>·</span> {candidate.office} <span>·</span> {candidate.party_code}</p></section>
      <section className="proposal-content">
        <div className="proposal-section-title"><div><p className="eyebrow">DOCUMENTOS ORIGINAIS</p><h2>{isLegislativeCandidate ? "Propostas para o mandato" : "Plano de governo"}</h2></div><span>{candidate.proposals.length} {candidate.proposals.length === 1 ? "arquivo" : "arquivos"}</span></div>
        {candidate.proposals.length ? <div className="document-list">{candidate.proposals.map((proposal, index) => <a className="document-row" key={proposal.file_name} href={`${BASE_PATH}${proposal.public_path}`} target="_blank" rel="noreferrer"><span className="document-number">{String(index + 1).padStart(2, "0")}</span><span className="document-file"><strong>{isLegislativeCandidate ? "Proposta para o mandato" : "Proposta de governo"}</strong><small>{proposal.file_name}</small></span><span className="document-format">PDF</span><span className="document-open" aria-label="Abrir arquivo">↗</span></a>)}</div> : <div className="empty-state"><h3>{candidate.office === "SENADOR" ? "Sem documento padronizado" : "Documento não localizado"}</h3><p>{candidate.office === "SENADOR" ? "O TSE não exige nem mantém um plano individual padronizado para o Senado. Veja abaixo as propostas localizadas em site ou documento individual vinculado pelo candidato." : "Não encontramos uma proposta associada a esta candidatura nos dados publicados."}</p></div>}
        {candidate.office === "SENADOR" && candidate.senatorProposal && <section className="plan-analysis senator-proposals">
          <div className="analysis-heading"><div><p className="eyebrow">FONTES INDIVIDUAIS VINCULADAS AO TSE</p><h2>Propostas por tema</h2></div><span>16 TEMAS · {candidate.senatorProposal.statements.length} TRECHOS</span></div>
          <p className="analysis-disclaimer">Trechos coletados somente de site ou documento vinculado pelo próprio candidato no cadastro do TSE. Não usamos posts de redes sociais nem programa partidário como substitutos de propostas individuais.</p>
          <div className="analysis-sections">{candidate.senatorProposal.sections.map((section) => <article className="analysis-section" key={section.id}>
            <div className="analysis-section-heading"><h3>{section.label}</h3><span>{section.excerpts.length} {section.excerpts.length === 1 ? "trecho" : "trechos"}</span></div>
            <p>{section.summary}</p>
            {section.excerpts.map((excerpt, index) => <div className="senator-evidence" key={`${excerpt.source_sha256}-${index}`}>
              <p>{excerpt.text}</p>
              <a className="source-link" href={excerpt.source_url} target="_blank" rel="noreferrer">{excerpt.source_title || "Fonte individual"} · {new Date(excerpt.collected_at).toLocaleDateString("pt-BR")} ↗</a>
            </div>)}
          </article>)}</div>
          {!candidate.senatorProposal.statements.length && <p className="analysis-summary">{candidate.senatorProposal.status === "no-candidate-website-in-tse" ? "O TSE não lista um site/documento individual para esta candidatura. Não localizamos propostas individuais nesta coleta." : candidate.senatorProposal.status === "site-unavailable-or-disallowed" ? "O site declarado não estava acessível ou não permitiu coleta automatizada." : candidate.senatorProposal.status === "official-site-without-extractable-proposals" ? "O site individual estava acessível, mas não encontramos trechos explícitos de propostas." : candidate.senatorProposal.status === "shared-site-without-individual-profile" ? "O endereço declarado leva a um site compartilhado, mas não foi possível confirmar ali um perfil individual." : "Não foi possível confirmar propostas individuais em uma fonte oficial."}</p>}
          {!candidate.senatorProposal.statements.length && candidate.senatorProposal.sources.length > 0 && <div className="document-list">{candidate.senatorProposal.sources.map((source) => <a className="document-row" key={source.url} href={source.url} target="_blank" rel="noreferrer"><span className="document-number">↗</span><span className="document-file"><strong>{source.title || "Site individual vinculado ao TSE"}</strong><small>{source.url}</small></span><span className="document-format">VERIFICADO</span></a>)}</div>}
          {!candidate.senatorProposal.statements.length && candidate.senatorProposal.sources.length === 0 && candidate.senatorProposal.declared_sites.length > 0 && <div className="document-list">{candidate.senatorProposal.declared_sites.map((url) => <a className="document-row" key={url} href={url} target="_blank" rel="noreferrer"><span className="document-number">↗</span><span className="document-file"><strong>Site declarado no cadastro do TSE</strong><small>{url}</small></span><span className="document-format">DECLARADO</span></a>)}</div>}
        </section>}
        {candidate.analyses.map((analysis) => <section className="plan-analysis" key={analysis.sha256}>
          <div className="analysis-heading"><div><p className="eyebrow">LEITURA ESTRUTURADA</p><h2>{isLegislativeCandidate ? "Resumo das propostas" : "Resumo do plano"}</h2></div><span>{analysis.method.startsWith("extractive-") ? "RESUMO EXTRATIVO" : analysis.method === "text-extraction-unavailable" ? "TEXTO NÃO EXTRAÍVEL" : "RESUMO ASSISTIDO POR IA · PRÉ-COMPUTADO"}</span></div>
          <p className="analysis-summary">{analysis.summary}</p>
          <div className="analysis-sections">{analysis.sections.map((section) => <article className="analysis-section" key={section.id}>
            <div className="analysis-section-heading"><h3>{section.title}</h3><span>{section.excerpts.length} {section.excerpts.length === 1 ? "trecho" : "trechos"}</span></div>
            <p>{section.summary}</p>
            {section.excerpts.map((excerpt) => <div className="senator-evidence" key={excerpt.id}>
              <p className="analysis-disclaimer">{excerpt.page_start === excerpt.page_end ? `Plano, p. ${excerpt.page_start}` : `Plano, p. ${excerpt.page_start}–${excerpt.page_end}`}</p>
              <p>{excerpt.text}</p>
            </div>)}
          </article>)}</div>
          <p className="analysis-disclaimer">Resumo pré-computado a partir do texto extraído do PDF; não substitui a proposta original. Os tópicos seguem uma taxonomia fixa e podem não representar todas as nuances do documento.</p>
        </section>)}
        <p className="source-note">{candidate.office === "SENADOR" ? "Propostas extraídas de site/documento individual vinculado pelo candidato no cadastro do TSE. Fonte de identificação: TSE, Dados Abertos, CC BY." : "Documento oficial apresentado à Justiça Eleitoral. Fonte: TSE, Dados Abertos, CC BY."} <a href="https://dadosabertos.tse.jus.br/dataset/candidatos-2026" target="_blank" rel="noreferrer">Consultar fonte ↗</a></p>
      </section>
    </> : <section className="proposal-content"><div className="empty-state"><h3>{error || (loaded ? "Candidatura não encontrada" : "Carregando proposta")}</h3><p>{error ? "Tente novamente mais tarde." : "Consulte a candidatura e os documentos oficiais do TSE."}</p><a href={`${BASE_PATH}/`}>Voltar às candidaturas</a></div></section>}
    <footer className="site-footer"><span>VOTO EM PAUTA <b>·</b> INFORMAÇÃO PARA ESCOLHER</span><span>Fonte: Tribunal Superior Eleitoral</span></footer>
  </main>;
}
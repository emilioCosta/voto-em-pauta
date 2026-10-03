"use client";

import initSqlJs, { type Database } from "sql.js";
import Image from "next/image";
import { useEffect, useState } from "react";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const PAGE_SIZE = 24;

type Candidate = {
  tse_candidate_id: string;
  state_code: string;
  office: string;
  full_name: string;
  ballot_name: string;
  party_code: string;
  party_name: string;
  ballot_number: string;
  registration_status: string;
  registration_detail: string;
  proposal_count: number;
  photo_path: string | null;
};
type Filters = { query: string; party: string; office: string; state: string; page: number };
type Party = { code: string; name: string };
type Result = { candidates: Candidate[]; total: number; page: number; pageCount: number };

const EMPTY_FILTERS: Filters = { query: "", party: "", office: "", state: "", page: 1 };

function allRows<T>(database: Database, query: string, values: (string | number)[] = []): T[] {
  try {
    const statement = database.prepare(query);
    try {
      statement.bind(values);
      const rows: T[] = [];
      while (statement.step()) rows.push(statement.getAsObject() as T);
      return rows;
    } finally {
      statement.free();
    }
  } catch (cause) {
    console.error("SQLite query failed:", query);
    throw cause;
  }
}

function readFilters(): Filters {
  const params = new URLSearchParams(window.location.search);
  const pageValue = Number.parseInt(params.get("page") ?? "1", 10);
  return {
    query: params.get("q")?.trim() ?? "",
    party: params.get("party") ?? "",
    office: params.get("office") ?? "",
    state: (params.get("state") ?? "").toUpperCase(),
    page: Number.isFinite(pageValue) && pageValue > 0 ? pageValue : 1,
  };
}

function makeResult(database: Database, filters: Filters): Result {
  const where = ["c.election_year = 2026"];
  const values: (string | number)[] = [];
  if (filters.query) {
    where.push("(c.full_name LIKE ? OR c.ballot_name LIKE ? OR c.tse_candidate_id = ?)");
    values.push(`%${filters.query}%`, `%${filters.query}%`, filters.query);
  }
  if (filters.party) { where.push("c.party_code = ?"); values.push(filters.party); }
  if (filters.office) { where.push("c.office = ?"); values.push(filters.office); }
  if (filters.state) { where.push("c.state_code = ?"); values.push(filters.state); }
  const clause = where.join(" AND ");
  const total = Number(allRows<{ total: number }>(database,
    `SELECT COUNT(*) AS total FROM candidates c WHERE ${clause}`, values)[0]?.total ?? 0);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(filters.page, pageCount);
  const candidates = allRows<Candidate>(database, `
    SELECT c.tse_candidate_id, c.state_code, c.office, c.full_name,
      c.ballot_name, c.party_code, c.party_name, c.ballot_number,
      c.registration_status, c.registration_detail,
      (SELECT COUNT(*) FROM proposals p WHERE p.candidate_id = c.tse_candidate_id) AS proposal_count,
      (SELECT public_path FROM candidate_photos p WHERE p.candidate_id = c.tse_candidate_id) AS photo_path
    FROM candidates c WHERE ${clause}
    ORDER BY c.state_code, c.office, c.ballot_name COLLATE NOCASE
    LIMIT ? OFFSET ?
  `, [...values, PAGE_SIZE, (page - 1) * PAGE_SIZE]);
  return { candidates, total, page, pageCount };
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("");
}

function paginationHref(filters: Filters, page: number) {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  if (filters.party) params.set("party", filters.party);
  if (filters.office) params.set("office", filters.office);
  if (filters.state) params.set("state", filters.state);
  params.set("page", String(page));
  return `${BASE_PATH}/?${params.toString()}`;
}

export default function CandidatesBrowser() {
  const [database, setDatabase] = useState<Database | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [parties, setParties] = useState<Party[]>([]);
  const [offices, setOffices] = useState<string[]>([]);
  const [states, setStates] = useState<string[]>([]);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let loadedDatabase: Database | undefined;
    async function loadDatabase() {
      try {
        const SQL = await initSqlJs({ locateFile: () => `${BASE_PATH}/vendor/sql-wasm.wasm` });
        const response = await fetch(`${BASE_PATH}/data/voto_em_pauta.sqlite3`);
        if (!response.ok) throw new Error("O snapshot de candidaturas ainda não foi publicado.");
        loadedDatabase = new SQL.Database(new Uint8Array(await response.arrayBuffer()));
        if (cancelled) { loadedDatabase.close(); return; }
        setParties(allRows<Party>(loadedDatabase,
          "SELECT DISTINCT party_code AS code, party_name AS name FROM candidates WHERE party_code IS NOT NULL ORDER BY party_name"));
        setOffices(allRows<{ office: string }>(loadedDatabase,
          "SELECT DISTINCT office FROM candidates WHERE office IS NOT NULL ORDER BY office").map((row) => row.office));
        setStates(allRows<{ state_code: string }>(loadedDatabase,
          "SELECT DISTINCT state_code FROM candidates WHERE state_code IS NOT NULL AND state_code <> 'BR' ORDER BY state_code").map((row) => row.state_code));
        setCandidateTotal(Number(allRows<{ total: number }>(loadedDatabase,
          "SELECT COUNT(*) AS total FROM candidates WHERE election_year = 2026")[0]?.total ?? 0));
        setFilters(readFilters());
        setDatabase(loadedDatabase);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Não foi possível carregar os dados do TSE.");
      }
    }
    void loadDatabase();
    return () => { cancelled = true; loadedDatabase?.close(); };
  }, []);

  const result = database ? makeResult(database, filters) : null;
  const activeFilters = Boolean(filters.query || filters.party || filters.office || filters.state);

  return (
    <main className="site-shell">
      <header className="topbar">
        <a className="brand" href={`${BASE_PATH}/`} aria-label="Voto em pauta, início"><span className="brand-mark" aria-hidden="true">VP</span><span>Voto em pauta</span></a>
        <div className="topbar-meta"><span className="live-dot" /> ELEIÇÕES GERAIS <strong>2026</strong></div>
        <a className="source-link" href="https://dadosabertos.tse.jus.br/dataset/candidatos-2026" target="_blank" rel="noreferrer">Fonte: TSE <span aria-hidden="true">↗</span></a>
      </header>

      <section className="intro-band"><div className="intro-inner">
        <div className="intro-copy"><p className="eyebrow">ELEIÇÕES 2026 <span>·</span> BRASIL</p><h1>Conheça quem<br /><em>quer seu voto.</em></h1><p className="intro-description">Candidaturas, partidos e propostas reunidos a partir dos dados oficiais da Justiça Eleitoral.</p></div>
        <div className="intro-stats" aria-label="Resumo das candidaturas"><div><strong>{candidateTotal.toLocaleString("pt-BR")}</strong><span>candidaturas</span></div><div><strong>{parties.length || "—"}</strong><span>partidos</span></div><div><strong>{offices.length || "—"}</strong><span>cargos</span></div></div>
        <div className="year-stamp" aria-hidden="true">BR<br /><b>26</b></div>
      </div></section>

      <section className="directory-section" aria-labelledby="directory-title">
        <div className="section-heading"><div><p className="eyebrow">DIRETÓRIO ELEITORAL</p><h2 id="directory-title">Candidaturas</h2></div><p className="result-total"><strong>{result?.total.toLocaleString("pt-BR") ?? "…"}</strong> resultados</p></div>
        <form className="filter-bar" action={`${BASE_PATH}/`} method="get">
          <label className="search-field"><span className="search-icon" aria-hidden="true">⌕</span><span className="sr-only">Pesquisar candidato</span><input type="search" name="q" placeholder="Nome ou nome de urna" value={filters.query} onChange={(event) => setFilters({ ...filters, query: event.target.value, page: 1 })} /></label>
          <label className="select-field"><span>PARTIDO</span><select name="party" value={filters.party} onChange={(event) => setFilters({ ...filters, party: event.target.value, page: 1 })}><option value="">Todos os partidos</option>{parties.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label>
          <label className="select-field"><span>DISPUTA</span><select name="office" value={filters.office} onChange={(event) => setFilters({ ...filters, office: event.target.value, page: 1 })}><option value="">Todos os cargos</option>{offices.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="select-field state-select"><span>UF</span><select name="state" value={filters.state} onChange={(event) => setFilters({ ...filters, state: event.target.value, page: 1 })}><option value="">Brasil</option>{states.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <button className="filter-submit" type="submit" aria-label="Aplicar filtros">Filtrar <span aria-hidden="true">→</span></button>
        </form>

        {activeFilters && <div className="active-filters"><span>FILTROS ATIVOS</span>{filters.query && <span className="filter-token">“{filters.query}”</span>}{filters.party && <span className="filter-token">{filters.party}</span>}{filters.office && <span className="filter-token">{filters.office}</span>}{filters.state && <span className="filter-token">{filters.state}</span>}<a href={`${BASE_PATH}/`}>Limpar filtros</a></div>}
        {error ? <div className="empty-state"><h3>Dados temporariamente indisponíveis</h3><p>{error}</p></div> : !result ? <div className="empty-state" role="status"><h3>Carregando candidaturas</h3><p>Preparando a base pública do TSE neste navegador.</p></div> : result.candidates.length ? (
          <div className="candidate-list">{result.candidates.map((candidate, index) => {
            const status = candidate.registration_status && !["#NE", "#NULO", "-"].includes(candidate.registration_status) ? candidate.registration_status : null;
            return <article className="candidate-row" key={candidate.tse_candidate_id}>
              <div className="candidate-index">{String((result.page - 1) * PAGE_SIZE + index + 1).padStart(2, "0")}</div>
              {candidate.photo_path ? <Image className="candidate-monogram candidate-photo" src={`${BASE_PATH}${candidate.photo_path}`} alt={`Foto de ${candidate.ballot_name || candidate.full_name}`} width={41} height={41} unoptimized /> : <div className="candidate-monogram" aria-hidden="true">{initials(candidate.ballot_name || candidate.full_name)}</div>}
              <div className="candidate-main"><p className="candidate-ballot">{candidate.ballot_name || candidate.full_name}</p><p className="candidate-fullname">{candidate.full_name}</p></div>
              <div className="candidate-office"><span>{candidate.office}</span><strong>{candidate.state_code === "BR" ? "BRASIL" : candidate.state_code}</strong>{status && <small>{status}</small>}</div>
              <div className="candidate-party"><strong>{candidate.party_code}</strong><span>{candidate.party_name}</span></div>
              <div className="candidate-number"><span>NÚMERO</span><strong>{candidate.ballot_number || "—"}</strong></div>
              <div className="candidate-action">{candidate.proposal_count > 0 ? <a className="proposal-link" href={`${BASE_PATH}/propostas/?candidate_id=${encodeURIComponent(candidate.tse_candidate_id)}`}><span className="document-icon" aria-hidden="true">▤</span> Proposta de governo <span className="proposal-count">{candidate.proposal_count}</span></a> : <span className="no-proposal">Plano não localizado</span>}</div>
            </article>;
          })}</div>
        ) : <div className="empty-state"><span className="empty-mark" aria-hidden="true">∅</span><h3>Nenhuma candidatura encontrada</h3><p>Altere os filtros ou tente buscar por outro nome.</p><a href={`${BASE_PATH}/`}>Limpar busca</a></div>}
        {result && result.total > PAGE_SIZE && <nav className="pagination" aria-label="Paginação de candidaturas"><span>PÁGINA <strong>{result.page}</strong> DE {result.pageCount}</span><div>{result.page > 1 && <a href={paginationHref(filters, result.page - 1)} aria-label="Página anterior">← Anterior</a>}{result.page < result.pageCount && <a href={paginationHref(filters, result.page + 1)} aria-label="Próxima página">Próxima →</a>}</div></nav>}
      </section>
      <footer className="site-footer"><span>VOTO EM PAUTA <b>·</b> INFORMAÇÃO PARA ESCOLHER</span><span>Fonte: Tribunal Superior Eleitoral <a href="https://dadosabertos.tse.jus.br/dataset/candidatos-2026" target="_blank" rel="noreferrer">CC BY ↗</a></span></footer>
    </main>
  );
}
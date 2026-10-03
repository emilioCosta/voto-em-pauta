from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "data" / "informe_eleitoral.sqlite3"
PUBLIC_DIR = ROOT / "public"
PUBLIC_DB = PUBLIC_DIR / "data" / "voto_em_pauta.sqlite3"
PUBLIC_INFO = PUBLIC_DIR / "data" / "source-info.json"
PROPOSAL_DIR = PUBLIC_DIR / "propostas"
PHOTO_DIR = PUBLIC_DIR / "fotos"
SQL_WASM_SOURCE = ROOT / "node_modules" / "sql.js" / "dist" / "sql-wasm.wasm"
SQL_WASM_TARGET = PUBLIC_DIR / "vendor" / "sql-wasm.wasm"
TSE_DATASET_URL = "https://dadosabertos.tse.jus.br/dataset/candidatos-{year}"
PLAN_MEMBER = re.compile(r"^(\d{4})([A-Z]{2})(\d+)_\d+\.pdf$", re.IGNORECASE)


def create_public_database(
    year: int,
    proposal_paths: list[dict[str, str]],
    photo_paths: list[dict[str, str]],
    sources: list[dict[str, str]],
) -> None:
    PUBLIC_DB.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_DB.unlink(missing_ok=True)
    public = sqlite3.connect(PUBLIC_DB)
    source = sqlite3.connect(f"file:{SOURCE_DB.as_posix()}?mode=ro", uri=True)
    try:
        public.executescript("""
            PRAGMA journal_mode = DELETE;
            PRAGMA foreign_keys = ON;
            CREATE TABLE candidates (
                tse_candidate_id TEXT PRIMARY KEY,
                election_year INTEGER NOT NULL,
                state_code TEXT,
                office TEXT,
                full_name TEXT,
                ballot_name TEXT,
                party_code TEXT,
                party_name TEXT,
                ballot_number TEXT,
                registration_status TEXT,
                registration_detail TEXT
            );
            CREATE TABLE candidacy_history (
                id INTEGER PRIMARY KEY,
                current_candidate_id TEXT NOT NULL,
                election_year INTEGER NOT NULL,
                state_code TEXT,
                office TEXT,
                candidate_name TEXT,
                ballot_name TEXT,
                party_code TEXT,
                party_name TEXT,
                registration_status TEXT,
                judgment_status TEXT,
                result_status TEXT
            );
            CREATE TABLE declared_assets (
                id INTEGER PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                item_number TEXT,
                item_type TEXT,
                declared_value TEXT
            );
            CREATE TABLE proposals (
                id INTEGER PRIMARY KEY,
                candidate_id TEXT NOT NULL REFERENCES candidates(tse_candidate_id),
                state_code TEXT NOT NULL,
                file_name TEXT NOT NULL,
                public_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                UNIQUE(candidate_id, file_name)
            );
            CREATE TABLE candidate_photos (
                candidate_id TEXT PRIMARY KEY REFERENCES candidates(tse_candidate_id),
                state_code TEXT NOT NULL,
                public_path TEXT NOT NULL,
                sha256 TEXT NOT NULL
            );
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY,
                resource_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                metadata_modified TEXT,
                license TEXT NOT NULL
            );
            CREATE INDEX idx_candidates_filters ON candidates(election_year, party_code, office, state_code);
            CREATE INDEX idx_candidates_search ON candidates(ballot_name, full_name);
            CREATE INDEX idx_history_candidate ON candidacy_history(current_candidate_id, election_year);
            CREATE INDEX idx_assets_candidate ON declared_assets(candidate_id);
            CREATE INDEX idx_proposals_candidate ON proposals(candidate_id);
        """)

        public.executemany("""
            INSERT INTO candidates (
                tse_candidate_id, election_year, state_code, office, full_name,
                ballot_name, party_code, party_name, ballot_number,
                registration_status, registration_detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, source.execute("""
            SELECT tse_candidate_id, election_year, state_code, office, full_name,
                   ballot_name, party_code, party_name, ballot_number,
                   registration_status, registration_detail
            FROM candidates WHERE election_year = ?
        """, (year,)).fetchall())
        public.executemany("""
            INSERT INTO candidacy_history (
                id, current_candidate_id, election_year, state_code, office,
                candidate_name, ballot_name, party_code, party_name,
                registration_status, judgment_status, result_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, source.execute("""
            SELECT id, current_candidate_id, election_year, state_code, office,
                   candidate_name, ballot_name, party_code, party_name,
                   registration_status, judgment_status, result_status
            FROM candidacy_history
        """).fetchall())
        public.executemany("""
            INSERT INTO declared_assets (id, candidate_id, item_number, item_type, declared_value)
            VALUES (?, ?, ?, ?, ?)
        """, source.execute("""
            SELECT id, tse_candidate_id, item_number, item_type, declared_value
            FROM declared_assets WHERE election_year = ?
        """, (year,)).fetchall())
        public.executemany("""
            INSERT INTO sources (id, resource_name, source_url, metadata_modified, license)
            VALUES (?, ?, ?, ?, ?)
        """, [
            (
                index, item["resource_name"], item["source_url"],
                item.get("metadata_modified"),
                "Creative Commons Atribuição (CC BY)",
            )
            for index, item in enumerate(sources, start=1)
        ])
        public.executemany("""
            INSERT INTO proposals (candidate_id, state_code, file_name, public_path, sha256)
            VALUES (?, ?, ?, ?, ?)
        """, [
            (
                item["candidate_id"], item["state_code"], item["file_name"],
                item["public_path"], item["sha256"],
            )
            for item in proposal_paths
        ])
        public.executemany("""
            INSERT INTO candidate_photos (candidate_id, state_code, public_path, sha256)
            VALUES (?, ?, ?, ?)
        """, [
            (item["candidate_id"], item["state_code"], item["public_path"], item["sha256"])
            for item in photo_paths
        ])
        public.execute("PRAGMA user_version = 1")
        public.commit()
        public.execute("VACUUM")
    finally:
        source.close()
        public.close()


def extract_public_proposals(year: int) -> list[dict[str, str]]:
    if PROPOSAL_DIR.exists():
        shutil.rmtree(PROPOSAL_DIR)
    PROPOSAL_DIR.mkdir(parents=True)
    source = sqlite3.connect(f"file:{SOURCE_DB.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        candidate_ids = {
            row[0] for row in source.execute(
                "SELECT tse_candidate_id FROM candidates WHERE election_year = ?", (year,)
            )
        }
        rows = source.execute("""
            SELECT p.state_code, p.file_name, p.archive_path, p.archive_member
            FROM proposal_documents p
            JOIN sources s ON s.id = p.source_id
            WHERE p.election_year = ? AND s.dataset_slug = ?
            ORDER BY p.state_code, p.file_name
        """, (year, f"candidatos-{year}")).fetchall()

        proposals: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            member_name = PurePosixPath(row["archive_member"]).name
            match = PLAN_MEMBER.fullmatch(member_name)
            if not match:
                continue
            doc_year, state_code, candidate_id = match.groups()
            if int(doc_year) != year or candidate_id not in candidate_ids or state_code != row["state_code"]:
                continue
            key = (candidate_id, member_name)
            if key in seen:
                continue
            seen.add(key)
            archive_path = ROOT / row["archive_path"]
            with zipfile.ZipFile(archive_path) as archive:
                info = archive.getinfo(row["archive_member"])
                if info.file_size <= 0 or info.file_size > 100 * 1024 * 1024:
                    raise ValueError(f"Tamanho PDF fora do intervalo aceito: {member_name}")
                target_dir = PROPOSAL_DIR / str(year) / state_code
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / member_name
                digest = hashlib.sha256()
                with archive.open(info) as input_file, target.open("wb") as output_file:
                    while chunk := input_file.read(1024 * 1024):
                        output_file.write(chunk)
                        digest.update(chunk)
            if target.read_bytes()[:5] != b"%PDF-":
                target.unlink(missing_ok=True)
                raise ValueError(f"Arquivo de proposta inválido: {member_name}")
            proposals.append({
                "candidate_id": candidate_id,
                "state_code": state_code,
                "file_name": member_name,
                "public_path": f"/propostas/{year}/{state_code}/{member_name}",
                "sha256": digest.hexdigest(),
            })
        return proposals
    finally:
        source.close()


def extract_public_photos(year: int) -> list[dict[str, str]]:
    photo_pattern = re.compile(r"^F([A-Z]{2})(\d+)_div\.jpe?g$", re.IGNORECASE)
    if PHOTO_DIR.exists():
        shutil.rmtree(PHOTO_DIR)
    PHOTO_DIR.mkdir(parents=True)
    source = sqlite3.connect(f"file:{SOURCE_DB.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        candidates = {
            row["tse_candidate_id"]: row["state_code"]
            for row in source.execute(
                "SELECT tse_candidate_id, state_code FROM candidates WHERE election_year = ?", (year,)
            )
        }
        archives = source.execute("""
            SELECT resource_name, local_path
            FROM sources
            WHERE dataset_slug = ? AND resource_name LIKE '%Fotos de candidatos'
            ORDER BY resource_name
        """, (f"candidatos-{year}",)).fetchall()

        photos: dict[str, dict[str, str]] = {}
        for row in archives:
            archive_path = ROOT / row["local_path"]
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    match = photo_pattern.fullmatch(PurePosixPath(info.filename).name)
                    if not match:
                        continue
                    state_code, candidate_id = match.groups()
                    state_code = state_code.upper()
                    if candidates.get(candidate_id) != state_code or info.file_size > 10 * 1024 * 1024:
                        continue
                    target_dir = PHOTO_DIR / str(year) / state_code
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / f"{candidate_id}.jpg"
                    digest = hashlib.sha256()
                    with archive.open(info) as input_file, target.open("wb") as output_file:
                        while chunk := input_file.read(256 * 1024):
                            output_file.write(chunk)
                            digest.update(chunk)
                    if target.read_bytes()[:2] != b"\xff\xd8":
                        target.unlink(missing_ok=True)
                        continue
                    photos[candidate_id] = {
                        "candidate_id": candidate_id,
                        "state_code": state_code,
                        "public_path": f"/fotos/{year}/{state_code}/{candidate_id}.jpg",
                        "sha256": digest.hexdigest(),
                    }
        return list(photos.values())
    finally:
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera arquivos estáticos públicos do TSE para GitHub Pages.")
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    if not SOURCE_DB.exists():
        raise SystemExit(f"Banco fonte ausente: {SOURCE_DB}")

    source = sqlite3.connect(f"file:{SOURCE_DB.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        sources = [dict(row) for row in source.execute("""
            SELECT resource_name, source_url, metadata_modified
            FROM sources
            WHERE dataset_slug = ? AND (
                resource_name = 'Candidatos' OR resource_name = 'Histórico de candidaturas'
                OR resource_name LIKE '%Proposta de governo'
                OR resource_name LIKE '%Fotos de candidatos'
            )
            ORDER BY resource_name
        """, (f"candidatos-{args.year}",))]
    finally:
        source.close()

    proposals = extract_public_proposals(args.year)
    photos = extract_public_photos(args.year)
    create_public_database(args.year, proposals, photos, sources)
    if not SQL_WASM_SOURCE.exists():
        raise SystemExit("sql.js ausente; execute npm ci antes da publicação estática.")
    SQL_WASM_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SQL_WASM_SOURCE, SQL_WASM_TARGET)
    public = sqlite3.connect(PUBLIC_DB)
    try:
        candidate_count = public.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    finally:
        public.close()
    PUBLIC_INFO.write_text(json.dumps({
        "election_year": args.year,
        "source_data_updated_at": max(
            (item["metadata_modified"] for item in sources if item.get("metadata_modified")),
            default=None,
        ),
        "source": TSE_DATASET_URL.format(year=args.year),
        "license": "Creative Commons Atribuição (CC BY)",
        "attribution": "Fonte: Tribunal Superior Eleitoral (TSE), Dados Abertos. CC BY.",
        "candidates": candidate_count,
        "proposal_documents": len(proposals),
        "candidate_photos": len(photos),
        "excluded_fields": ["CPF", "e-mail", "telefone", "título eleitoral", "descrições livres de bens/endereço"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Snapshot público: {PUBLIC_DB.relative_to(ROOT)}")
    print(f"Candidaturas e histórico exportados; propostas: {len(proposals)}; fotos: {len(photos)}")
    print(f"SQLite: {PUBLIC_DB.stat().st_size / (1024 * 1024):.1f} MB; PDFs: {sum(path.stat().st_size for path in PROPOSAL_DIR.rglob('*.pdf')) / (1024 * 1024):.1f} MB; fotos: {sum(path.stat().st_size for path in PHOTO_DIR.rglob('*.jpg')) / (1024 * 1024):.1f} MB")


if __name__ == "__main__":
    main()
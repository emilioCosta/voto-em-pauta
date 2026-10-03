from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import unicodedata
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = DATA_DIR / "source_files"
PROPOSAL_DIR = DATA_DIR / "proposals"
DATABASE_PATH = DATA_DIR / "informe_eleitoral.sqlite3"
CKAN_API = "https://dadosabertos.tse.jus.br/api/3/action/package_show?id={}"
DATASETS = {
    "candidatos-{year}": "candidaturas",
    "prestacao-de-contas-eleitorais-{year}": "contas",
    "processual-{year}": "processos_eleitorais",
}
SENSITIVE_HEADER_PARTS = (
    "CPF", "EMAIL", "TELEFONE", "CELULAR", "ENDERECO", "CEP",
    "TITULO_ELEITOR", "IDENTIDADE", "DOCUMENTO_IDENTIDADE",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "resource"


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "informe-eleitoral/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if not payload.get("success"):
        raise RuntimeError(f"Falha consultando CKAN: {url}")
    return payload["result"]


def selected_resources(year: int, public_only: bool = False) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for package_template, category in DATASETS.items():
        slug = package_template.format(year=year)
        if public_only and category != "candidaturas":
            continue
        package = request_json(CKAN_API.format(slug))
        for resource in package.get("resources", []):
            name = normalize(resource.get("name", ""))
            if category == "candidaturas":
                if public_only:
                    wanted = name in {
                        "candidatos", "bens de candidatos", "historico de candidaturas"
                    } or "proposta de governo" in name
                else:
                    wanted = (
                        name in {
                            "candidatos", "bens de candidatos", "historico de candidaturas",
                            "redes sociais de candidatos",
                        }
                        or "proposta de governo" in name
                    )
            elif category == "contas":
                wanted = name == "prestacao de contas de candidatos"
            else:
                wanted = True
            if wanted and resource.get("url"):
                selected.append({
                    "dataset_slug": slug,
                    "dataset_title": package.get("title", slug),
                    "category": category,
                    "resource_id": resource["id"],
                    "resource_name": resource.get("name", "resource"),
                    "source_url": resource["url"],
                    "metadata_modified": resource.get("metadata_modified"),
                })
    return selected


def download_resource(resource: dict[str, Any], refresh: bool) -> dict[str, Any]:
    folder = ARCHIVE_DIR / resource["dataset_slug"]
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{safe_name(resource['resource_name'])}_{resource['resource_id'][:8]}.zip"
    if refresh or not destination.exists():
        request = urllib.request.Request(
            resource["source_url"], headers={"User-Agent": "informe-eleitoral/0.1"}
        )
        temporary = destination.with_suffix(".zip.part")
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    byte_size += len(chunk)
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        sha256 = digest.hexdigest()
    else:
        digest = hashlib.sha256()
        byte_size = 0
        with destination.open("rb") as source_file:
            while chunk := source_file.read(1024 * 1024):
                digest.update(chunk)
                byte_size += len(chunk)
        sha256 = digest.hexdigest()
    return {
        **resource,
        "local_path": str(destination.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256,
        "byte_size": byte_size,
        "retrieved_at": utc_now(),
    }


def decode_csv(payload: bytes) -> tuple[list[dict[str, str]], list[str]]:
    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = payload.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise UnicodeError("Não foi possível decodificar o CSV")
    sample = text[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [str(header or "").strip().lstrip("\ufeff") for header in (reader.fieldnames or [])]
    if not headers:
        return [], []
    rows = []
    for row in reader:
        cleaned = {
            (key or "").strip().lstrip("\ufeff"): (value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        rows.append(cleaned)
    return rows, headers


def sanitized_record(row: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in row.items()
        if not any(part in normalize(key).replace(" ", "_").upper() for part in SENSITIVE_HEADER_PARTS)
    }


def value_for(row: dict[str, str], *keys: str) -> str | None:
    indexed = {normalize(key).replace(" ", "_"): value for key, value in row.items()}
    for key in keys:
        value = indexed.get(normalize(key).replace(" ", "_"))
        if value:
            return value
    return None


def insert_source(connection: sqlite3.Connection, item: dict[str, Any]) -> int:
    cursor = connection.execute(
        """INSERT INTO sources (
            dataset_slug, dataset_title, resource_id, resource_name, source_url,
            local_path, sha256, byte_size, retrieved_at, metadata_modified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(resource_id) DO UPDATE SET
            dataset_title=excluded.dataset_title, resource_name=excluded.resource_name,
            source_url=excluded.source_url, local_path=excluded.local_path,
            sha256=excluded.sha256, byte_size=excluded.byte_size,
            retrieved_at=excluded.retrieved_at, metadata_modified=excluded.metadata_modified
        RETURNING id""",
        (
            item["dataset_slug"], item["dataset_title"], item["resource_id"],
            item["resource_name"], item["source_url"], item["local_path"],
            item["sha256"], item["byte_size"], item["retrieved_at"],
            item.get("metadata_modified"),
        ),
    )
    return int(cursor.fetchone()[0])


def import_csv(connection: sqlite3.Connection, item: dict[str, Any], source_id: int, member: str, payload: bytes, year: int) -> int:
    rows, _ = decode_csv(payload)
    resource_name = normalize(item["resource_name"])
    is_candidate_file = resource_name == "candidatos"
    is_asset_file = resource_name == "bens de candidatos"
    is_history_file = resource_name == "historico de candidaturas"
    for row_number, row in enumerate(rows, start=1):
        if is_candidate_file:
            candidate_id = value_for(row, "SQ_CANDIDATO", "ID_CANDIDATO")
            if candidate_id:
                connection.execute(
                    """INSERT INTO candidates (
                        election_year, tse_candidate_id, state_code, office, full_name,
                        ballot_name, party_code, party_name, ballot_number,
                        registration_status, registration_detail, source_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(election_year, tse_candidate_id) DO UPDATE SET
                        state_code=excluded.state_code, office=excluded.office,
                        full_name=excluded.full_name, ballot_name=excluded.ballot_name,
                        party_code=excluded.party_code, party_name=excluded.party_name,
                        ballot_number=excluded.ballot_number,
                        registration_status=excluded.registration_status,
                        registration_detail=excluded.registration_detail, source_id=excluded.source_id""",
                    (
                        int(value_for(row, "ANO_ELEICAO") or year), candidate_id,
                        value_for(row, "SG_UF"), value_for(row, "DS_CARGO"),
                        value_for(row, "NM_CANDIDATO"), value_for(row, "NM_URNA_CANDIDATO"),
                        value_for(row, "SG_PARTIDO"), value_for(row, "NM_PARTIDO"),
                        value_for(row, "NR_CANDIDATO"),
                        value_for(row, "DS_SITUACAO_CANDIDATURA"),
                        value_for(row, "DS_DETALHE_SITUACAO_CAND"), source_id,
                    ),
                )
        elif is_asset_file:
            candidate_id = value_for(row, "SQ_CANDIDATO", "ID_CANDIDATO")
            if candidate_id:
                connection.execute(
                    """INSERT INTO declared_assets (
                        election_year, tse_candidate_id, item_number, item_type,
                        description, declared_value, source_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(value_for(row, "ANO_ELEICAO") or year), candidate_id,
                        value_for(row, "NR_ORDEM_BEM_CANDIDATO"),
                        value_for(row, "DS_TIPO_BEM_CANDIDATO"),
                        value_for(row, "DS_BEM_CANDIDATO"),
                        value_for(row, "VR_BEM_CANDIDATO"), source_id,
                    ),
                )
        elif is_history_file:
            candidate_id = value_for(row, "SQ_CANDIDATO_ATUAL")
            election_year = value_for(row, "ANO_ELEICAO")
            if candidate_id and election_year:
                connection.execute(
                    """INSERT OR IGNORE INTO candidacy_history (
                        current_candidate_id, election_year, state_code, office,
                        candidate_name, ballot_name, party_code, party_name,
                        registration_status, judgment_status, result_status, source_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        candidate_id, int(election_year), value_for(row, "SG_UF"),
                        value_for(row, "DS_CARGO"), value_for(row, "NM_CANDIDATO"),
                        value_for(row, "NM_URNA_CANDIDATO"), value_for(row, "SG_PARTIDO"),
                        value_for(row, "NM_PARTIDO"),
                        value_for(row, "DS_SITUACAO_CANDIDATURA"),
                        value_for(row, "DS_SITUACAO_JULGAMENTO"),
                        value_for(row, "DS_SIT_TOT_TURNO"), source_id,
                    ),
                )
    return len(rows)


def import_resource(connection: sqlite3.Connection, item: dict[str, Any], year: int) -> int:
    source_id = insert_source(connection, item)
    archive_path = ROOT / item["local_path"]
    total_rows = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_name = member.filename
            suffix = PurePosixPath(member_name).suffix.casefold()
            resource_name = normalize(item["resource_name"])
            if suffix in {".csv", ".txt"} and resource_name in {
                "candidatos", "bens de candidatos", "historico de candidaturas"
            }:
                total_rows += import_csv(
                    connection, item, source_id, member_name, archive.read(member), year
                )
            elif suffix == ".pdf" and "proposta de governo" in normalize(item["resource_name"]):
                state_code = "BR" if " br " in f" {normalize(item['resource_name'])} " else ""
                if not state_code:
                    match = re.search(r"\b([A-Z]{2})\b", item["resource_name"].upper())
                    state_code = match.group(1) if match else "NA"
                file_name = Path(member_name).name
                connection.execute(
                    """INSERT OR IGNORE INTO proposal_documents
                    (election_year, state_code, file_name, archive_path, archive_member, source_id)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        year, state_code, file_name, item["local_path"], member_name, source_id,
                    ),
                )
    return total_rows


def write_manifest(items: list[dict[str, Any]]) -> None:
    year = items[0]["dataset_slug"].rsplit("-", 1)[-1]
    manifest_path = DATA_DIR / f"download-manifest-{year}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"generated_at": utc_now(), "sources": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Baixa fontes públicas do TSE e recria o SQLite local.")
    parser.add_argument("--year", type=int, default=2026, help="Ano eleitoral (padrão: 2026).")
    parser.add_argument("--refresh", action="store_true", help="Baixa novamente mesmo se o ZIP já existir.")
    parser.add_argument("--offline", action="store_true", help="Usa apenas ZIPs já arquivados localmente.")
    parser.add_argument("--public-only", action="store_true", help="Baixa apenas candidaturas, histórico e planos para publicação estática; não busca bens, contas nem processos.")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA_DIR / f"download-manifest-{args.year}.json"
    if args.offline:
        if not manifest_path.exists():
            legacy_manifest = DATA_DIR / "download-manifest.json"
            if legacy_manifest.exists():
                manifest_path = legacy_manifest
        if not manifest_path.exists():
            raise SystemExit(f"Manifesto ausente para modo offline: {manifest_path}")
        archived = json.loads(manifest_path.read_text(encoding="utf-8")).get("sources", [])
        for item in archived:
            if not (ROOT / item["local_path"]).exists():
                raise SystemExit(f"Arquivo ausente em modo offline: {item['local_path']}")
    else:
        resources = selected_resources(args.year, public_only=args.public_only)
        if not resources:
            raise SystemExit("O catálogo CKAN não retornou recursos selecionados.")
        archived = []
        for resource in resources:
            archived.append(download_resource(resource, args.refresh))
            print(f"Arquivo pronto: {archived[-1]['resource_name']}")
    write_manifest(archived)

    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{DATABASE_PATH}{suffix}").unlink(missing_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        for table in (
            "proposal_documents", "candidacy_history", "declared_assets",
            "candidates", "source_rows", "sources",
        ):
            connection.execute(f"DELETE FROM {table}")
        row_total = 0
        for item in archived:
            row_total += import_resource(connection, item, args.year)
            print(f"Importado: {item['resource_name']}")
        connection.commit()
        candidate_count = connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        asset_count = connection.execute("SELECT COUNT(*) FROM declared_assets").fetchone()[0]
        history_count = connection.execute("SELECT COUNT(*) FROM candidacy_history").fetchone()[0]
        document_count = connection.execute("SELECT COUNT(*) FROM proposal_documents").fetchone()[0]
        source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        print(f"Banco: {DATABASE_PATH.relative_to(ROOT)}")
        print(f"Fontes: {source_count}; linhas principais: {row_total}; candidaturas: {candidate_count}; bens: {asset_count}; histórico: {history_count}; propostas: {document_count}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()

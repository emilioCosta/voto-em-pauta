from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from analyze_plans import TOPICS, classify_topics, extractive_summary, normalize

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "data" / "informe_eleitoral.sqlite3"
OUTPUT_DIR = ROOT / "public" / "data" / "senator-proposals"
USER_AGENT = "VotoEmPautaResearch/0.1 (+https://github.com/emilioCosta/voto-em-pauta)"
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
MAX_PAGES_PER_CANDIDATE = 5
REQUEST_DELAY_SECONDS = 0.75

SOCIAL_HOSTS = {
    "instagram.com", "facebook.com", "x.com", "twitter.com", "tiktok.com",
    "youtube.com", "youtu.be", "threads.com", "threads.net", "whatsapp.com",
    "chat.whatsapp.com", "wa.me", "linkedin.com", "t.me", "telegram.me",
    "kwai.com", "k.kwai.com", "kwai-video.com", "flickr.com", "spotify.com",
    "open.spotify.com", "linktr.ee", "bsky.app", "soundcloud.com", "gettr.com",
    "truthsocial.com", "rumble.com", "pinterest.com", "tumblr.com", "twibbonize.com",
    "twb.nz", "sticker.ly", "giphy.com", "deezer.com", "tidal.com", "biolink.info",
    "lnk.bio",
}
SOURCE_TERMS = ("proposta", "plano", "prioridade", "compromisso", "agenda estrategica", "eixo", "bandeira", "projeto")
ACTION_TERMS = re.compile(
    r"\b(vou|vamos|defenderei|defenderemos|pretendo|proponho|propomos|assumo|"
    r"nosso compromisso|meu compromisso|ser[aá] criado|ser[aá] implantado|"
    r"ser[aá] implementado|ser[aá] prioridade|ter[aá] prioridade|prioridade para|"
    r"priorizar|criaremos|ampliaremos|garantiremos|implementaremos|reduziremos|"
    r"fortaleceremos|construiremos|trabalharei|atuarei|levarei|queremos|"
    r"quero|defender|apoiar|promover|instituir)\b",
    re.IGNORECASE,
)
RETROSPECTIVE_TERMS = (
    "resultados por municipio", "entregas realizadas", "leis sancionadas", "trajetoria",
    "mandato anterior", "historia", "biografia", "quem sou", "quem e", "resultados do mandato",
    "campanha", "materiais oficiais", "redes sociais", "perguntas frequentes", "faq",
    "contato", "participar", "cadastro",
)
PROMOTIONAL_TERMS = re.compile(
    r"\b(acesse|clique|baixe|download|espalhe|divulgue|cadastre-se|preencha|"
    r"receba|entre no grupo|siga minhas redes|vote\s+\d{1,3}|conhe[cç]a minha hist[oó]ria)\b",
    re.IGNORECASE,
)
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "button"}
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p", "li"}


class CampaignPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.blocks: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.current_tag = ""
        self.current_parts: list[str] = []
        self.current_section = ""
        self.current_section_active = False
        self.anchor_href = ""
        self.anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name") or ""
            if key:
                self.meta[key.casefold()] = attributes.get("content", "")
        if tag == "a" and attributes.get("href"):
            self.anchor_href = attributes["href"]
            self.anchor_parts = []
        if tag in BLOCK_TAGS:
            self._flush_block()
            self.current_tag = tag
            self.current_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.anchor_href:
            label = self._join(self.anchor_parts)
            self.anchors.append({"href": self.anchor_href, "label": label})
            self.anchor_href = ""
            self.anchor_parts = []
        if tag == self.current_tag and tag in BLOCK_TAGS:
            text = self._join(self.current_parts)
            if text:
                if tag in {"h1", "h2", "h3", "h4"}:
                    self.current_section = text
                    section_text = normalize(text)
                    self.current_section_active = any(term in section_text for term in SOURCE_TERMS)
                    self.blocks.append({"tag": tag, "text": text, "section": text, "active": str(self.current_section_active)})
                else:
                    self.blocks.append({
                        "tag": tag,
                        "text": text,
                        "section": self.current_section,
                        "active": str(self.current_section_active),
                    })
            self.current_tag = ""
            self.current_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        if self.current_tag:
            self.current_parts.append(data)
        if self.anchor_href:
            self.anchor_parts.append(data)

    def _flush_block(self) -> None:
        if self.current_tag:
            text = self._join(self.current_parts)
            if text:
                self.blocks.append({
                    "tag": self.current_tag,
                    "text": text,
                    "section": self.current_section,
                    "active": str(self.current_section_active),
                })
        self.current_tag = ""
        self.current_parts = []

    @staticmethod
    def _join(parts: list[str]) -> str:
        return re.sub(r"\s+", " ", html.unescape(" ".join(parts))).strip()

    @property
    def title(self) -> str:
        return self._join(self.title_parts)


def canonical_url(raw_url: str) -> str | None:
    raw_url = raw_url.strip().rstrip(".,;)")
    raw_url = re.sub(r"^site\s*:\s*", "", raw_url, flags=re.IGNORECASE)
    if not raw_url.casefold().startswith(("http://", "https://")):
        if not re.fullmatch(r"(?:www\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}(?:/[^\s]*)?", raw_url):
            return None
        raw_url = f"https://{raw_url}"
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    host = parsed.hostname.casefold().removeprefix("www.")
    if not any(char == "." for char in host) or any(char.isspace() for char in host):
        return None
    if any(host == item or host.endswith(f".{item}") for item in SOCIAL_HOSTS):
        return None
    try:
        ascii_host = parsed.netloc.encode("idna").decode("ascii")
        path = urllib.parse.quote(urllib.parse.unquote(parsed.path or "/"), safe="/%:@!$&'()*+,;=-._~")
        query = urllib.parse.quote(urllib.parse.unquote(parsed.query), safe="/?@!$&'()*+,;=:%-._~")
        return urllib.parse.urlunsplit((parsed.scheme.casefold(), ascii_host, path, query, ""))
    except (UnicodeError, ValueError):
        return None


def clean_evidence(text: str) -> str:
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[e-mail removido]", text)
    text = re.sub(r"(?<!\w)(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?9?\d{4}[- .]?\d{4}(?!\w)", "[telefone removido]", text)
    return re.sub(r"\s+", " ", text).strip()[:1200]


def classify_proposal_topics(section_title: str, text: str) -> list[str]:
    combined = f"{section_title} {text}"
    normalized_title = normalize(section_title)
    topics = set(classify_topics(text))
    for topic in TOPICS:
        if normalize(topic["label"]) in normalized_title:
            topics.add(topic["id"])
    return [topic["id"] for topic in TOPICS if topic["id"] in topics][:4]


def proposal_statements(blocks: list[dict[str, str]], source_url: str, page_title: str, content_hash: str) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in blocks:
        if block["tag"] not in {"p", "li"}:
            continue
        text = block["text"]
        normalized_text = normalize(text)
        normalized_section = normalize(block["section"])
        if any(term in normalized_section for term in RETROSPECTIVE_TERMS):
            continue
        if PROMOTIONAL_TERMS.search(text):
            continue
        if not (block["active"] == "True" or ACTION_TERMS.search(normalized_text)):
            continue
        if not ACTION_TERMS.search(normalized_text):
            continue
        if len(text) < 45 or re.fullmatch(r"[\W\d_]+", text):
            continue
        fingerprint = normalize(text)[:500]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        statements.append({
            "text": clean_evidence(text),
            "section_title": block["section"],
            "topics": classify_proposal_topics(block["section"], text),
            "source_url": source_url,
            "source_title": page_title,
            "source_sha256": content_hash,
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        if len(statements) >= 30:
            break
    return statements


def candidate_slugs(candidate: dict[str, str]) -> set[str]:
    values = {candidate.get("ballot_name", ""), candidate.get("full_name", "")}
    return {
        re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalize(value))).strip("-")
        for value in values if value
    } - {""}


def robots_allowed(url: str, cache: dict[str, urllib.robotparser.RobotFileParser | None]) -> bool:
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in cache:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            request = urllib.request.Request(parser.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=12) as response:
                parser.parse(response.read(512 * 1024).decode("utf-8", errors="replace").splitlines())
            cache[origin] = parser
        except urllib.error.HTTPError as error:
            if error.code == 404:
                parser.parse(["User-agent: *", "Allow: /"])
                cache[origin] = parser
            else:
                cache[origin] = None
        except (urllib.error.URLError, TimeoutError, OSError):
            cache[origin] = None
    parser = cache[origin]
    return bool(parser and parser.can_fetch(USER_AGENT, url))


def fetch_page(url: str, robots_cache: dict[str, urllib.robotparser.RobotFileParser | None]) -> tuple[str, str, bytes] | None:
    if not robots_allowed(url, robots_cache):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            final_url = response.geturl()
            if urllib.parse.urlsplit(final_url).hostname != urllib.parse.urlsplit(url).hostname:
                return None
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return None
            return content_type, charset, body
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, UnicodeError, ValueError):
        return None


def parse_html(body: bytes, charset: str = "utf-8") -> CampaignPageParser:
    parser = CampaignPageParser()
    parser.feed(body.decode(charset, errors="replace"))
    parser.close()
    return parser


def pdf_statements(body: bytes, url: str) -> list[dict[str, Any]]:
    try:
        import pymupdf

        with pymupdf.open(stream=body, filetype="pdf") as document:
            text = "\n".join(page.get_text("text") for page in document[:80])
    except Exception:
        return []
    digest = hashlib.sha256(body).hexdigest()
    statements = []
    for line in text.splitlines():
        value = re.sub(r"\s+", " ", line).strip()
        if len(value) < 60 or not ACTION_TERMS.search(normalize(value)):
            continue
        statements.append({
            "text": clean_evidence(value),
            "section_title": "",
            "topics": classify_proposal_topics("", value),
            "source_url": url,
            "source_title": Path(urllib.parse.urlsplit(url).path).name or "Documento PDF",
            "source_sha256": digest,
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        if len(statements) >= 30:
            break
    return statements


def collect_candidate(candidate: dict[str, str], urls: list[str], shared_hosts: set[str], robots_cache: dict[str, urllib.robotparser.RobotFileParser | None]) -> dict[str, Any]:
    candidate_id = candidate["tse_candidate_id"]
    slugs = candidate_slugs(candidate)
    eligible_urls = []
    for raw_url in urls:
        url = canonical_url(raw_url)
        if not url:
            continue
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        if host in shared_hosts and parts.path.strip("/"):
            normalized_path = normalize(parts.path).replace(" ", "-")
            if not any(slug in normalized_path for slug in slugs):
                continue
        if url not in eligible_urls:
            eligible_urls.append(url)

    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "state_code": candidate["state_code"],
        "ballot_name": candidate["ballot_name"],
        "party_code": candidate["party_code"],
        "declared_sites": [],
        "sources": [],
        "statements": [],
        "status": "no-candidate-website-in-tse",
    }
    if not eligible_urls:
        return result
    result["declared_sites"] = eligible_urls

    seen_pages: set[str] = set()
    requests_made = 0
    succeeded = False
    for website_url in eligible_urls:
        if requests_made >= MAX_PAGES_PER_CANDIDATE:
            break
        origin_host = urllib.parse.urlsplit(website_url).hostname
        queued = [website_url]
        visited_site: set[str] = set()
        while queued and requests_made < MAX_PAGES_PER_CANDIDATE:
            page_url = queued.pop(0)
            if page_url in visited_site or page_url in seen_pages:
                continue
            visited_site.add(page_url)
            seen_pages.add(page_url)
            fetched = fetch_page(page_url, robots_cache)
            requests_made += 1
            time.sleep(REQUEST_DELAY_SECONDS)
            if not fetched:
                continue
            content_type, charset, body = fetched
            succeeded = True
            digest = hashlib.sha256(body).hexdigest()
            if content_type == "application/pdf" or page_url.casefold().endswith(".pdf"):
                result["statements"].extend(pdf_statements(body, page_url))
                result["sources"].append({"url": page_url, "title": Path(urllib.parse.urlsplit(page_url).path).name, "sha256": digest, "kind": "official-candidate-document", "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                continue
            if "html" not in content_type:
                continue
            page = parse_html(body, charset)
            page_parts = urllib.parse.urlsplit(page_url)
            shared_root = (page_parts.hostname or "") in shared_hosts and not page_parts.path.strip("/")
            if shared_root:
                for anchor in page.anchors:
                    href = urllib.parse.urljoin(page_url, anchor["href"])
                    parts = urllib.parse.urlsplit(href)
                    if parts.hostname != origin_host or parts.scheme not in {"http", "https"}:
                        continue
                    normalized_target = normalize(f"{anchor['label']} {parts.path}").replace(" ", "-")
                    if any(slug in normalized_target for slug in slugs):
                        queued.append(href)
                queued = queued[:MAX_PAGES_PER_CANDIDATE - requests_made]
                if queued:
                    continue
                result["status"] = "shared-site-without-individual-profile"
                continue
            result["sources"].append({"url": page_url, "title": page.title, "sha256": digest, "kind": "official-candidate-site", "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            result["statements"].extend(proposal_statements(page.blocks, page_url, page.title, digest))
            for anchor in page.anchors:
                href = urllib.parse.urljoin(page_url, anchor["href"])
                parts = urllib.parse.urlsplit(href)
                if parts.hostname != origin_host or parts.scheme not in {"http", "https"}:
                    continue
                hint = normalize(anchor["label"] + " " + parts.path)
                if any(term in hint for term in SOURCE_TERMS) and href not in visited_site:
                    queued.append(href)
            queued = queued[:MAX_PAGES_PER_CANDIDATE - requests_made]
        if requests_made >= MAX_PAGES_PER_CANDIDATE:
            break

    unique_statements = []
    fingerprints: set[str] = set()
    for statement in result["statements"]:
        fingerprint = normalize(statement["text"])
        if fingerprint and fingerprint not in fingerprints:
            fingerprints.add(fingerprint)
            unique_statements.append(statement)
    result["statements"] = unique_statements[:40]
    if result["statements"]:
        result["status"] = "proposals-found"
    elif result["status"] == "shared-site-without-individual-profile":
        pass
    elif succeeded:
        result["status"] = "official-site-without-extractable-proposals"
    else:
        result["status"] = "site-unavailable-or-disallowed"
    return result


def postprocess_existing(links_by_candidate: dict[str, list[str]]) -> None:
    host_owners: dict[str, set[str]] = defaultdict(set)
    for candidate_id, urls in links_by_candidate.items():
        for raw_url in urls:
            url = canonical_url(raw_url)
            if url:
                host_owners[urllib.parse.urlsplit(url).hostname or ""].add(candidate_id)
    shared_hosts = {host for host, owners in host_owners.items() if len(owners) > 1}
    topics = [{"id": topic["id"], "label": topic["label"]} for topic in TOPICS]
    counts: dict[str, dict[str, int]] = {}
    for path in OUTPUT_DIR.glob("*.json"):
        if path.name == "index.json":
            continue
        shard = json.loads(path.read_text(encoding="utf-8"))
        for candidate in shard.get("candidates", []):
            slugs = candidate_slugs(candidate)
            declared_sites = []
            for raw_url in links_by_candidate.get(candidate["candidate_id"], []):
                url = canonical_url(raw_url)
                if not url:
                    continue
                parts = urllib.parse.urlsplit(url)
                if parts.hostname in shared_hosts and parts.path.strip("/"):
                    normalized_path = normalize(parts.path).replace(" ", "-")
                    if not any(slug in normalized_path for slug in slugs):
                        continue
                if url not in declared_sites:
                    declared_sites.append(url)
            candidate["declared_sites"] = declared_sites
            if candidate.get("status") == "official-site-without-extractable-proposals" and not candidate.get("sources"):
                for raw_url in links_by_candidate.get(candidate["candidate_id"], []):
                    url = canonical_url(raw_url)
                    if url and urllib.parse.urlsplit(url).hostname in shared_hosts:
                        candidate["status"] = "shared-site-without-individual-profile"
                        break
            for statement in candidate.get("statements", []):
                statement["topics"] = classify_proposal_topics(statement.get("section_title", ""), statement.get("text", ""))
            candidate["sections"] = []
            for topic in TOPICS:
                excerpts = [
                    statement for statement in candidate.get("statements", [])
                    if topic["id"] in statement.get("topics", [])
                ]
                summary = (
                    extractive_summary(" ".join(item["text"] for item in excerpts), limit=2)
                    if excerpts else "Não foi observado no material consultado para esta candidatura."
                )
                candidate["sections"].append({
                    "id": topic["id"],
                    "label": topic["label"],
                    "summary": summary,
                    "excerpts": excerpts,
                })
        path.write_text(json.dumps(shard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state = shard.get("state_code", path.stem)
        entries = shard.get("candidates", [])
        counts[state] = {
            "candidates": len(entries),
            "with_proposals": sum(entry.get("status") == "proposals-found" for entry in entries),
        }
    index = {
        "year": 2026,
        "source": "URLs declaradas pelo candidato no recurso Redes sociais de candidatos do TSE; somente sites/documentos, sem extração de redes sociais ou atribuição de programa partidário.",
        "topics": topics,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "partitions": {
            state: {
                "path": f"/data/senator-proposals/{state}.json",
                **counts[state],
            }
            for state in sorted(counts)
        },
    }
    (OUTPUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    global REQUEST_DELAY_SECONDS
    parser = argparse.ArgumentParser(description="Extrai propostas explícitas de sites declarados por candidatos ao Senado no TSE.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--candidate-id", help="Limita a coleta a uma candidatura para teste.")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_SECONDS)
    parser.add_argument("--postprocess-existing", action="store_true", help="Recalcula rótulos/status nos shards locais sem acessar sites.")
    args = parser.parse_args()
    REQUEST_DELAY_SECONDS = max(0.0, args.delay)

    connection = sqlite3.connect(SOURCE_DB)
    connection.row_factory = sqlite3.Row
    try:
        candidates = [dict(row) for row in connection.execute(
            "SELECT tse_candidate_id, state_code, ballot_name, party_code FROM candidates "
            "WHERE election_year = ? AND office = 'SENADOR' ORDER BY state_code, ballot_name",
            (args.year,),
        )]
        links_by_candidate: dict[str, list[str]] = defaultdict(list)
        candidate_by_id = {row["tse_candidate_id"]: row for row in candidates}
        rows = connection.execute(
            "SELECT candidate_id, url FROM candidate_social_links WHERE state_code IS NOT NULL ORDER BY candidate_id, order_number"
        )
        for row in rows:
            if row["candidate_id"] in candidate_by_id:
                links_by_candidate[row["candidate_id"]].append(row["url"])
    finally:
        connection.close()

    if args.postprocess_existing:
        postprocess_existing(links_by_candidate)
        print("Shards existentes reclassificados sem requisições externas.")
        return

    if args.candidate_id:
        candidates = [row for row in candidates if row["tse_candidate_id"] == args.candidate_id]
    host_owners: dict[str, set[str]] = defaultdict(set)
    for candidate_id, urls in links_by_candidate.items():
        for raw_url in urls:
            url = canonical_url(raw_url)
            if url:
                host_owners[urllib.parse.urlsplit(url).hostname or ""].add(candidate_id)
    shared_hosts = {host for host, owners in host_owners.items() if len(owners) > 1}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
    by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        try:
            entry = collect_candidate(candidate, links_by_candidate.get(candidate["tse_candidate_id"], []), shared_hosts, robots_cache)
        except Exception as error:
            entry = {
                "candidate_id": candidate["tse_candidate_id"],
                "state_code": candidate["state_code"],
                "ballot_name": candidate["ballot_name"],
                "party_code": candidate["party_code"],
                "declared_sites": [],
                "sources": [],
                "statements": [],
                "status": f"collection-error:{type(error).__name__}",
            }
        by_state[candidate["state_code"]].append(entry)
        print(f"{candidate['state_code']} {candidate['ballot_name']}: {entry['status']}; fontes {len(entry['sources'])}; propostas {len(entry['statements'])}")

    index = {
        "year": args.year,
        "source": "URLs declaradas pelo candidato no recurso Redes sociais de candidatos do TSE; somente sites/documentos, sem extração de redes sociais ou atribuição de programa partidário.",
        "topics": [{"id": topic["id"], "label": topic["label"]} for topic in TOPICS],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "partitions": {},
    }
    generated: set[Path] = set()
    for state_code, entries in sorted(by_state.items()):
        path = OUTPUT_DIR / f"{state_code}.json"
        path.write_text(json.dumps({
            "state_code": state_code,
            "topics": index["topics"],
            "candidates": entries,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        generated.add(path)
        index["partitions"][state_code] = {
            "path": f"/data/senator-proposals/{state_code}.json",
            "candidates": len(entries),
            "with_proposals": sum(entry["status"] == "proposals-found" for entry in entries),
        }
    index_path = OUTPUT_DIR / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generated.add(index_path)
    for stale in OUTPUT_DIR.glob("*.json"):
        if stale not in generated:
            stale.unlink()
    print(f"Senadores processados: {sum(map(len, by_state.values()))}; domínios compartilhados ignorados: {len(shared_hosts)}")


if __name__ == "__main__":
    main()
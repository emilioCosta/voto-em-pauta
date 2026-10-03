from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
PROPOSAL_DIR = PUBLIC_DIR / "propostas"
ANALYSIS_FILE = PUBLIC_DIR / "data" / "plan-analysis.json"
TAXONOMY_VERSION = "1.0"
ANALYSIS_VERSION = "1.6"
MAX_PAGES = 120
MAX_SECTIONS = 32
MAX_LLM_CHARS = 48_000

TOPICS: list[dict[str, Any]] = [
    {"id": "education", "label": "Educação", "keywords": ["educacao", "escola", "ensino", "professor", "alfabetizacao", "creche", "universidade", "aprendizagem"]},
    {"id": "health", "label": "Saúde", "keywords": ["saude", "hospital", "atencao basica", "sus", "vacina", "medico", "saude mental", "medicamento"]},
    {"id": "public-safety", "label": "Segurança pública", "keywords": ["seguranca publica", "policia", "violencia", "crime", "faccoes", "sistema prisional", "defesa civil", "fronteiras"]},
    {"id": "economy-jobs", "label": "Economia e emprego", "keywords": ["economia", "emprego", "trabalho", "renda", "empreendedorismo", "industria", "comercio", "desenvolvimento economico"]},
    {"id": "tax-budget", "label": "Orçamento e tributos", "keywords": ["orcamento", "tributo", "imposto", "arrecadacao", "responsabilidade fiscal", "gasto publico", "divida publica"]},
    {"id": "social-protection", "label": "Proteção social", "keywords": ["assistencia social", "protecao social", "pobreza", "desigualdade", "transferencia de renda", "seguranca alimentar", "populacao vulneravel"]},
    {"id": "infrastructure-mobility", "label": "Infraestrutura e mobilidade", "keywords": ["infraestrutura", "mobilidade", "transporte", "rodovia", "ferrovia", "porto", "aeroporto", "logistica", "transito"]},
    {"id": "housing-sanitation", "label": "Moradia e saneamento", "keywords": ["habitacao", "moradia", "saneamento", "agua potavel", "esgoto", "residuos solidos", "urbanismo"]},
    {"id": "environment-climate", "label": "Meio ambiente e clima", "keywords": ["meio ambiente", "mudanca climatica", "clima", "desmatamento", "biodiversidade", "conservacao", "queimadas", "sustentabilidade"]},
    {"id": "agriculture-rural", "label": "Agropecuária e desenvolvimento rural", "keywords": ["agricultura", "agropecuaria", "agronegocio", "agricultura familiar", "producao rural", "reforma agraria", "agricultor", "pesca"]},
    {"id": "science-digital", "label": "Ciência, inovação e digital", "keywords": ["ciencia", "inovacao", "tecnologia", "transformacao digital", "inteligencia artificial", "pesquisa", "conectividade", "internet"]},
    {"id": "culture-sports-tourism", "label": "Cultura, esporte e turismo", "keywords": ["cultura", "esporte", "turismo", "patrimonio cultural", "lazer", "economia criativa"]},
    {"id": "rights-inclusion", "label": "Direitos e inclusão", "keywords": ["direitos humanos", "inclusao", "igualdade racial", "mulheres", "pessoa com deficiencia", "povos indigenas", "juventude", "diversidade"]},
    {"id": "governance", "label": "Gestão pública e transparência", "keywords": ["gestao publica", "governanca", "transparencia", "participacao social", "controle social", "combate a corrupcao", "servico publico", "desburocratizacao"]},
    {"id": "energy", "label": "Energia e mineração", "keywords": ["energia", "eletricidade", "transicao energetica", "mineracao", "petroleo", "gas natural", "fontes renovaveis"]},
    {"id": "justice-defense", "label": "Justiça e defesa", "keywords": ["justica", "judiciario", "defesa nacional", "forcas armadas", "sistema de justica", "direito penal"]},
]
TOPIC_IDS = {topic["id"] for topic in TOPICS}
STOPWORDS = set("a ao aos as com como da das de do dos e em entre essa esse esta este foi fora ha isso isto mais mas na nas no nos o os ou para pela pelas pelo pelos por que se sem sob sua suas seu seus um uma umas uns ja ser sao ter tem todo toda todos todas onde quando muito pode podem governo plano proposta propostas".split())
logging.getLogger("pypdf").setLevel(logging.ERROR)


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def clean_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_heading(line: str) -> bool:
    value = line.strip()
    if len(value) < 4 or len(value) > 120 or re.search(r"[.!?;]$", value):
        return False
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(char.isupper() for char in letters) / len(letters)
    numbered = re.match(r"^(?:eixo|cap[ií]tulo|diretriz|pilar|parte)\s+(?:\d+|[ivx]+)|^proposta\s+\d+\s*:|^\d+(?:\.\d+)*[.)]\s", value, re.I)
    return bool(numbered) or (upper_ratio >= 0.84 and 2 <= len(value.split()) <= 14)


def extract_sections(pdf_path: Path) -> list[dict[str, Any]]:
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as reader:
            page_texts = [page.get_text("text") for page in reader[:MAX_PAGES]]
    except Exception as error:
        print(f"Aviso: PyMuPDF não pôde extrair {pdf_path.name} ({type(error).__name__}).")
        return []
    return sections_from_page_texts(page_texts)


def sections_from_page_texts(page_texts: list[str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_title = "Apresentação"
    current_start = 1
    current_page = 1
    current_lines: list[str] = []

    def flush(end_page: int) -> None:
        body = clean_text("\n".join(current_lines))
        if len(body) >= 160:
            sections.append({
                "id": f"s{len(sections) + 1:02d}",
                "title": current_title,
                "page_start": current_start,
                "page_end": end_page,
                "text": body,
            })

    for page_number, raw_text in enumerate(page_texts, start=1):
        current_page = page_number
        text = clean_text(raw_text)
        normalized_page = normalize(text[:4000])
        compact_page = re.sub(r"\s+", "", normalized_page)
        numbered_entries = len(re.findall(r"(?m)^\s*\d{1,2}\.\s+", text))
        toc_entries = len(re.findall(r"\bproposta\s+\d+\b", normalized_page))
        has_contents_marker = "sumario" in compact_page or "indice" in compact_page or "contents" in compact_page
        if page_number <= 10 and (has_contents_marker or numbered_entries >= 4 or toc_entries >= 8):
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                current_lines.append("")
                continue
            normalized_line = normalize(line).replace(" ", "")
            if normalized_line.startswith("programadegoverno"):
                continue
            if re.match(r"^saulo\s+arcangeli\s+e\s+preta\s+lu\s+[–-]\s+\d{4}$", line, re.IGNORECASE):
                continue
            if page_number <= 10 and normalize(line) in {"introducao", "apresentacao"}:
                current_lines = []
                current_title = line.title()
                current_start = page_number
                continue
            if is_heading(line) and len(" ".join(current_lines).strip()) >= 160:
                flush(page_number)
                current_title = line[:120]
                current_start = page_number
                current_lines = []
            else:
                current_lines.append(line)
            if len(sections) >= MAX_SECTIONS:
                break
        if len(sections) >= MAX_SECTIONS:
            break

    flush(current_page)
    return sections


def classify_topics(text: str) -> list[str]:
    normalized = normalize(text)
    scores: list[tuple[int, str]] = []
    for topic in TOPICS:
        hits = sum(normalized.count(normalize(keyword)) for keyword in topic["keywords"])
        explicit_phrase = any(
            len(keyword.split()) > 1 and normalize(keyword) in normalized
            for keyword in topic["keywords"]
        )
        if hits >= 2 or explicit_phrase:
            scores.append((hits, topic["id"]))
    scores.sort(reverse=True)
    return [topic_id for _, topic_id in scores[:4]]


def split_sentences(text: str) -> list[str]:
    joined_text = re.sub(r"\s*\n\s*", " ", text)
    sentences = [
        re.sub(r"\s+", " ", sentence).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", joined_text)
        if len(sentence.strip()) >= 45
    ]
    if sentences:
        return sentences

    fragments: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        current.append(line)
        current_length += len(line)
        if current_length >= 180:
            fragments.append(" ".join(current))
            current = []
            current_length = 0
    if current:
        fragments.append(" ".join(current))
    return [fragment for fragment in fragments if len(fragment) >= 45]


def extractive_summary(text: str, limit: int = 3) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return "O PDF não forneceu texto extraível; consulte o documento original."
    useful = [
        sentence for sentence in sentences
        if len(sentence) >= 65 and not re.fullmatch(r"[\W\d_]+", sentence)
        and not re.match(r"^(?:sum[aá]rio|eixo\s+\d+|proposta\s+\d+)\b", sentence, re.I)
    ]
    selected = useful[:limit] if useful else sentences[:limit]
    return " ".join(selected)[:1200]


def local_analysis(sections: list[dict[str, Any]]) -> dict[str, Any]:
    if not sections:
        return {
            "summary": "Não foi possível extrair texto automaticamente deste PDF. Consulte a proposta original.",
            "sections": [],
            "method": "text-extraction-unavailable",
        }
    for section in sections:
        section["topics"] = classify_topics(section["text"])
        section["summary"] = extractive_summary(section["text"], limit=2)
        del section["text"]
    topical_sections = [section for section in sections if section["topics"] and section["summary"]]
    summary_parts = [f"{section['title']}: {section['summary']}" for section in topical_sections[:4]]
    full_summary = " ".join(summary_parts)[:2400] or extractive_summary(
        " ".join(section["summary"] for section in sections), limit=3
    )
    return {"summary": full_summary, "sections": sections, "method": f"extractive-v{ANALYSIS_VERSION}"}


def llm_analysis(sections: list[dict[str, Any]], api_key: str, model: str, base_url: str) -> dict[str, Any]:
    section_inputs = []
    remaining = MAX_LLM_CHARS
    for section in sections:
        excerpt = section["text"][:min(3000, remaining)]
        remaining -= len(excerpt)
        if not excerpt:
            break
        section_inputs.append({"id": section["id"], "title": section["title"], "pages": [section["page_start"], section["page_end"]], "text": excerpt})
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Resuma planos de governo em português com fidelidade estrita ao texto. Não invente políticas, prazos, custos nem resultados. Separe promessas explícitas de contexto. Classifique cada trecho apenas nos tópicos fornecidos. Responda JSON com summary e sections, cada section contendo id, summary e topics."},
            {"role": "user", "content": json.dumps({"topics": [{"id": item["id"], "label": item["label"]} for item in TOPICS], "sections": section_inputs}, ensure_ascii=False)},
        ],
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.load(response)
            content = result["choices"][0]["message"]["content"]
            analysis = json.loads(content)
            section_by_id = {section["id"]: section for section in sections}
            output_sections = []
            for item in analysis.get("sections", []):
                original = section_by_id.get(item.get("id"))
                if not original:
                    continue
                topics = [topic for topic in item.get("topics", []) if topic in TOPIC_IDS]
                output_sections.append({
                    "id": original["id"], "title": original["title"],
                    "page_start": original["page_start"], "page_end": original["page_end"],
                    "summary": str(item.get("summary", ""))[:1200],
                    "topics": topics,
                })
            return {"summary": str(analysis.get("summary", ""))[:2400], "sections": output_sections, "method": f"{model}"}
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            if isinstance(error, urllib.error.HTTPError) and error.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"LLM analysis failed: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrai e classifica planos de governo uma vez por hash do PDF.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--use-llm", action="store_true", help="Use OPENAI_API_KEY para gerar resumo abstrativo somente para PDFs sem análise armazenada ou com hash alterado.")
    args = parser.parse_args()

    previous: dict[str, dict[str, Any]] = {}
    if ANALYSIS_FILE.exists():
        try:
            old = json.loads(ANALYSIS_FILE.read_text(encoding="utf-8"))
            if old.get("analysis_version") == ANALYSIS_VERSION and old.get("taxonomy_version") == TAXONOMY_VERSION:
                previous = {item["sha256"]: item for item in old.get("documents", [])}
        except (json.JSONDecodeError, KeyError, TypeError):
            previous = {}

    import sqlite3

    database_path = PUBLIC_DIR / "data" / "voto_em_pauta.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        documents = connection.execute(
            "SELECT candidate_id, state_code, file_name, public_path, sha256 "
            "FROM proposals ORDER BY candidate_id, file_name"
        ).fetchall()
    finally:
        connection.close()

    use_llm = args.use_llm and bool(os.environ.get("OPENAI_API_KEY"))
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    results: list[dict[str, Any]] = []
    reused = 0
    for candidate_id, state_code, file_name, public_path, expected_hash in documents:
        cached = previous.get(expected_hash)
        cached_method = cached.get("method", "") if cached else ""
        if cached and (not use_llm or cached_method == model):
            analysis = {key: cached[key] for key in ("summary", "sections", "method") if key in cached}
            reused += 1
        else:
            pdf_path = PUBLIC_DIR / public_path.lstrip("/")
            text_sections = extract_sections(pdf_path)
            if text_sections:
                analysis = local_analysis([dict(section) for section in text_sections])
            else:
                analysis = {
                    "summary": "Não foi possível extrair texto automaticamente deste PDF. Consulte a proposta original.",
                    "sections": [],
                    "method": "text-extraction-unavailable",
                }
            if use_llm and text_sections:
                try:
                    llm = llm_analysis(text_sections, os.environ["OPENAI_API_KEY"], model, base_url)
                    if llm.get("summary") and llm.get("sections"):
                        analysis = llm
                except RuntimeError as error:
                    print(f"Aviso: {file_name}: {error}; mantendo resumo extrativo.")
        results.append({
            "candidate_id": candidate_id,
            "state_code": state_code,
            "file_name": file_name,
            "public_path": public_path,
            "sha256": expected_hash,
            **analysis,
        })

    output = {
        "analysis_version": ANALYSIS_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "source": "TSE, Dados Abertos; resumos gerados e armazenados por hash do PDF.",
        "summary_policy": "Análises são pré-computadas no workflow e servidas como JSON estático; requisições de visitantes não chamam modelos de IA.",
        "topics": [{"id": topic["id"], "label": topic["label"]} for topic in TOPICS],
        "documents": results,
    }
    ANALYSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Análises de plano: {len(results)}; reutilizadas pelo hash: {reused}; geradas/reprocessadas: {len(results) - reused}; LLM: {'ativado' if use_llm else 'desativado'}")


if __name__ == "__main__":
    main()

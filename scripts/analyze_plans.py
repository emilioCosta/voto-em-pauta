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
ANALYSIS_DIR = PUBLIC_DIR / "data" / "plan-analysis"
TAXONOMY_VERSION = "1.0"
ANALYSIS_VERSION = "2.18"
MAX_PAGES = 120
MAX_SECTIONS = 32
MAX_LLM_CHARS = 48_000

TOPICS: list[dict[str, Any]] = [
    {"id": "education", "label": "Educação", "keywords": ["educacao", "educacao publica", "politica educacional", "escola", "escolas", "escola publica", "escolas publicas", "ensino", "ensino publico", "ensino medio", "ensino superior", "educacao infantil", "educacao basica", "professor", "professores", "alfabetizacao", "creche", "creches", "universidade", "universidades", "aprendizagem", "tempo integral"]},
    {"id": "health", "label": "Saúde", "keywords": ["saude", "saude publica", "politica de saude", "sistema unico de saude", "hospital", "hospitais", "hospital publico", "hospitais publicos", "atendimento de saude", "atencao basica", "saude da familia", "sus", "vacina", "medico", "medicos", "atendimento medico", "saude mental", "medicamento"]},
    {"id": "public-safety", "label": "Segurança pública", "keywords": ["seguranca publica", "politica de seguranca", "policia", "policias", "violencia policial", "violencia", "crime organizado", "crime", "faccoes", "sistema prisional", "defesa civil", "fronteiras"]},
    {"id": "economy-jobs", "label": "Economia e emprego", "keywords": ["economia", "politica economica", "crescimento economico", "economia brasileira", "emprego", "emprego formal", "geracao de emprego", "geracao de empregos", "mercado de trabalho", "trabalho digno", "trabalho decente", "salario minimo", "renda minima", "empreendedorismo", "industria", "comercio", "desenvolvimento economico"]},
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
    text = re.sub(r"(?<!\w)(?:[A-ZÀ-ÖØ-Þ]\s+){1,}[A-ZÀ-ÖØ-Þ](?!\w)", lambda match: re.sub(r"\s+", "", match.group()), text)
    text = re.sub(r"\b(\d)\s+X\s+(\d)\b", r"\1X\2", text)
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", text)
    deduplicated_lines: list[str] = []
    previous_normalized_line = ""
    for line in text.splitlines():
        normalized_line = normalize(re.sub(r"\s+", " ", line).strip())
        if normalized_line and normalized_line == previous_normalized_line:
            continue
        deduplicated_lines.append(line)
        previous_normalized_line = normalized_line
    text = "\n".join(deduplicated_lines)
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
            page_texts = [extract_page_text(page) for page in reader[:MAX_PAGES]]
    except Exception as error:
        print(f"Aviso: PyMuPDF não pôde extrair {pdf_path.name} ({type(error).__name__}).")
        return []
    return sections_from_page_texts(page_texts)


def extract_page_text(page: Any) -> str:
    plain_text = page.get_text("text")
    spaced_runs = re.findall(r"(?<!\w)((?:[A-ZÀ-ÖØ-Þ]\s+){2,}[A-ZÀ-ÖØ-Þ])(?!\w)", plain_text)
    meaningful_runs = [
        run for run in spaced_runs
        if len(re.sub(r"\s+", "", run)) >= 9
        and re.sub(r"\s+", "", normalize(run)) not in "programadegoverno"
    ]
    if not meaningful_runs:
        return plain_text
    blocks: list[str] = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type", 0) != 0:
            continue
        lines: list[str] = []
        for line in block.get("lines", []):
            spans = [repair_letter_spaced_span(span) for span in line.get("spans", [])]
            line_text = " ".join(part for part in spans if part.strip()).strip()
            if line_text:
                lines.append(line_text)
        if lines:
            merged_lines: list[str] = []
            for line_text in lines:
                letters = [character for character in line_text if character.isalpha()]
                uppercase_fragment = bool(letters) and sum(character.isupper() for character in letters) / len(letters) >= 0.84 and len(line_text) <= 120
                if uppercase_fragment and merged_lines:
                    previous_letters = [character for character in merged_lines[-1] if character.isalpha()]
                    previous_uppercase = bool(previous_letters) and sum(character.isupper() for character in previous_letters) / len(previous_letters) >= 0.84
                    if previous_uppercase and not re.search(r"[.!?;]$", merged_lines[-1]):
                        merged_lines[-1] = f"{merged_lines[-1]} {line_text}"
                        continue
                merged_lines.append(line_text)
            blocks.append("\n".join(merged_lines))
    return "\n\n".join(blocks)


def repair_letter_spaced_span(span: dict[str, Any]) -> str:
    span_characters = span.get("chars", [])
    text = span.get("text") or "".join(item.get("c", "") for item in span_characters)
    if not re.fullmatch(r"\s*(?:[A-ZÀ-ÖØ-Þ0-9]\s+){1,}[A-ZÀ-ÖØ-Þ0-9]\s*", text):
        return text
    characters = [item for item in span_characters if not item.get("c", "").isspace()]
    if len(characters) < 2:
        return text
    output = [characters[0]["c"]]
    font_size = float(span.get("size", 12))
    gap_threshold = max(2.0, font_size * 0.12)
    previous_right = characters[0]["bbox"][2]
    for character in characters[1:]:
        if character["bbox"][0] - previous_right > gap_threshold:
            output.append(" ")
        output.append(character["c"])
        previous_right = character["bbox"][2]
    repaired = "".join(output)
    return re.sub(r"(?<=\d)X(?=\d)", " X ", repaired)


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
            letters = [char for char in line if char.isalpha()]
            uppercase_fragment = bool(letters) and sum(char.isupper() for char in letters) / len(letters) >= 0.84 and not re.search(r"[.!?;]$", line)
            if not " ".join(current_lines).strip() and is_heading(current_title) and uppercase_fragment and (len(letters) >= 2 or any(char.isdigit() for char in line)):
                current_title = f"{current_title} {line}"[:120]
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


def classify_section_topics(title: str, text: str) -> list[str]:
    topic_ids = set(classify_topics(text))
    normalized_title = normalize(title)
    for topic in TOPICS:
        label = normalize(topic["label"])
        if label in normalized_title or any(
            normalize(keyword) in normalized_title
            for keyword in topic["keywords"]
        ):
            topic_ids.add(topic["id"])
    return [topic["id"] for topic in TOPICS if topic["id"] in topic_ids][:4]


def topic_has_evidence(topic: dict[str, Any], text: str) -> bool:
    normalized = normalize(text)
    return any(
        len(keyword.split()) > 1 and normalize(keyword) in normalized
        for keyword in topic["keywords"]
    )


def remove_embedded_heading(text: str, source_title: str = "") -> str:
    text = deduplicate_repeated_phrases(re.sub(r"\s+", " ", text).strip())
    if source_title:
        text = re.sub(rf"^\s*{re.escape(source_title)}\s*[:;,.—-]*\s*", "", text, count=1, flags=re.IGNORECASE)
    chunks = re.split(r"(?<=[.!?])\s+|\s+[•●▪]\s+", text)
    cleaned_chunks: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        standalone_heading = re.fullmatch(r"""["'“”‘’]*([A-ZÀ-ÖØ-Þ0-9]+(?:\s+[A-ZÀ-ÖØ-Þ0-9]+){1,11})[.!?;,:]*""", chunk)
        if standalone_heading:
            heading_words = standalone_heading.group(1).split()
            if len(heading_words) > 1 or heading_words[0] in {"FIM", "PLANO", "PROGRAMA", "PROPOSTA"}:
                continue
        uppercase_heading = re.match(r"^((?:[A-ZÀ-ÖØ-Þ]{2,}|[A-ZÀ-ÖØ-Þ])(?:\s+(?:[A-ZÀ-ÖØ-Þ]{2,}|[A-ZÀ-ÖØ-Þ])){0,11})\s+(?=[A-ZÀ-ÖØ-Þ][a-zà-öø-þ])", chunk)
        if uppercase_heading:
            heading = uppercase_heading.group(1).strip()
            heading_words = heading.split()
            if len(heading_words) > 1 or heading_words[0] in {"FIM", "PLANO", "PROGRAMA", "PROPOSTA"}:
                chunk = chunk[uppercase_heading.end():].strip()
        label_match = re.match(r"""^["'“”‘’]*([^:;]{3,180})[:;]\s+(.+)$""", chunk)
        if label_match:
            label = label_match.group(1).strip()
            remainder = label_match.group(2).strip()
            label_words = label.split()
            normalized_heading = normalize(label)
            proposal_verbs = ("garantir", "ampliar", "criar", "fortalecer", "defender", "implementar", "reduzir", "aumentar", "construir", "promover", "assegurar", "trabalhar", "investir", "expandir")
            has_action = any(normalized_heading.startswith(verb) for verb in proposal_verbs)
            title_like = len(label_words) <= 20 and any(char.isupper() for char in label)
            if title_like and not has_action and len(remainder) > 15:
                chunk = remainder
                standalone_heading = re.fullmatch(r"""["'“”‘’]*([A-ZÀ-ÖØ-Þ0-9]+(?:\s+[A-ZÀ-ÖØ-Þ0-9]+){1,11})[.!?;,:]*""", chunk)
                if standalone_heading:
                    continue
        if chunk:
            cleaned_chunks.append(chunk)
    text = " ".join(cleaned_chunks)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


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
    return deduplicate_repeated_phrases(" ".join(selected))[:1200]


def deduplicate_repeated_phrases(text: str) -> str:
    tokens = text.split()
    if len(tokens) < 6:
        return text
    normalized_tokens = [normalize(re.sub(r"^\W+|\W+$", "", token)) for token in tokens]
    output: list[str] = []
    index = 0
    while index < len(tokens):
        maximum_width = min(12, (len(tokens) - index) // 2)
        duplicate_width = 0
        for width in range(maximum_width, 2, -1):
            left = normalized_tokens[index:index + width]
            right = normalized_tokens[index + width:index + width * 2]
            if all(left) and left == right:
                duplicate_width = width
                break
        if duplicate_width:
            output.extend(tokens[index:index + duplicate_width])
            repeat_count = 2
            while (
                index + duplicate_width * (repeat_count + 1) <= len(tokens)
                and normalized_tokens[index:index + duplicate_width]
                == normalized_tokens[index + duplicate_width * repeat_count:index + duplicate_width * (repeat_count + 1)]
            ):
                repeat_count += 1
            index += duplicate_width * repeat_count
            continue
        output.append(tokens[index])
        index += 1

    cleaned = " ".join(output)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def local_analysis(sections: list[dict[str, Any]]) -> dict[str, Any]:
    if not sections:
        return {
            "summary": "Não foi possível extrair texto automaticamente deste PDF. Consulte a proposta original.",
            "sections": [
                {
                    "id": topic["id"],
                    "title": topic["label"],
                    "page_start": None,
                    "page_end": None,
                    "topics": [topic["id"]],
                    "summary": "Não foi possível verificar: texto do plano não extraível.",
                    "excerpts": [],
                }
                for topic in TOPICS
            ],
            "method": "text-extraction-unavailable",
        }

    section_topics: list[dict[str, Any]] = []
    for section in sections:
        text = section["text"]
        section_topics.append({
            "id": section["id"],
            "title": section["title"],
            "page_start": section["page_start"],
            "page_end": section["page_end"],
            "text": text,
            "topics": classify_section_topics(section["title"], text),
            "excerpt": extractive_summary(text, limit=2),
        })

    topic_sections: list[dict[str, Any]] = []
    for topic in TOPICS:
        excerpts: list[dict[str, Any]] = []
        for section in section_topics:
            sentences = split_sentences(section["text"])
            relevant_sentences = [sentence for sentence in sentences if topic_has_evidence(topic, sentence)]
            title_matches_topic = normalize(topic["label"]) in normalize(section["title"])
            if not relevant_sentences and (title_matches_topic or topic_has_evidence(topic, section["title"])):
                relevant_sentences = sentences[:2]
            if not relevant_sentences:
                continue
            excerpt_text = remove_embedded_heading(" ".join(relevant_sentences[:2]), section["title"])[:1200]
            if excerpt_text:
                excerpts.append({
                    "id": section["id"],
                    "page_start": section["page_start"],
                    "page_end": section["page_end"],
                    "text": excerpt_text,
                })
        summary = (
            extractive_summary(" ".join(excerpt["text"] for excerpt in excerpts), limit=3)
            if excerpts else "Não foi observado no plano."
        )
        topic_sections.append({
            "id": topic["id"],
            "title": topic["label"],
            "page_start": min((excerpt["page_start"] for excerpt in excerpts), default=None),
            "page_end": max((excerpt["page_end"] for excerpt in excerpts), default=None),
            "topics": [topic["id"]],
            "summary": summary,
            "excerpts": excerpts,
        })

    summary_sentences: list[str] = []
    seen_summary_sentences: set[str] = set()
    for section in topic_sections:
        if not section["excerpts"]:
            continue
        for sentence in split_sentences(section["summary"]):
            sentence = remove_embedded_heading(sentence)
            if len(sentence) < 45:
                continue
            fingerprint = normalize(sentence)
            if not fingerprint or fingerprint in seen_summary_sentences:
                continue
            candidate_summary = " ".join([*summary_sentences, sentence])
            if len(candidate_summary) > 2400:
                break
            summary_sentences.append(sentence)
            seen_summary_sentences.add(fingerprint)
        if len(" ".join(summary_sentences)) >= 2200:
            break
    full_summary = remove_embedded_heading(deduplicate_repeated_phrases(" ".join(summary_sentences))) or "Não foi possível extrair propostas temáticas do plano."
    return {"summary": full_summary, "sections": topic_sections, "method": f"extractive-v{ANALYSIS_VERSION}"}


def analysis_category(office: str) -> str:
    normalized_office = normalize(office).upper()
    exact_categories = {
        "PRESIDENTE": "presidente",
        "VICE-PRESIDENTE": "vice-presidente",
        "GOVERNADOR": "governador",
        "VICE-GOVERNADOR": "vice-governador",
        "SENADOR": "senador",
        "1º SUPLENTE": "senador",
        "2º SUPLENTE": "senador",
    }
    if normalized_office in exact_categories:
        return exact_categories[normalized_office]
    if normalized_office.startswith("DEPUTADO "):
        return "deputado"
    return re.sub(r"[^a-z0-9]+", "-", normalize(office)).strip("-") or "outros"


def cached_analyses() -> dict[str, dict[str, Any]]:
    cached: dict[str, dict[str, Any]] = {}
    source_files = [ANALYSIS_FILE, *ANALYSIS_DIR.rglob("*.json")] if ANALYSIS_DIR.exists() else [ANALYSIS_FILE]
    for source_file in source_files:
        if not source_file.is_file():
            continue
        try:
            old = json.loads(source_file.read_text(encoding="utf-8"))
            if old.get("analysis_version") != ANALYSIS_VERSION or old.get("taxonomy_version") != TAXONOMY_VERSION:
                continue
            for item in old.get("documents", []):
                if isinstance(item, dict) and item.get("sha256"):
                    cached[item["sha256"]] = item
        except (json.JSONDecodeError, OSError, AttributeError, TypeError):
            continue
    return cached


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

    previous = cached_analyses()

    import sqlite3

    database_path = PUBLIC_DIR / "data" / "voto_em_pauta.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        documents = connection.execute(
            "SELECT p.candidate_id, p.state_code, p.file_name, p.public_path, p.sha256, c.office "
            "FROM proposals p JOIN candidates c ON c.tse_candidate_id = p.candidate_id "
            "ORDER BY c.office, p.state_code, p.candidate_id, p.file_name"
        ).fetchall()
    finally:
        connection.close()

    use_llm = args.use_llm and bool(os.environ.get("OPENAI_API_KEY"))
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    grouped_results: dict[tuple[str, str], list[dict[str, Any]]] = {}
    reused = 0
    for candidate_id, state_code, file_name, public_path, expected_hash, office in documents:
        cached = previous.get(expected_hash)
        cached_method = cached.get("method", "") if cached else ""
        if cached and (not use_llm or cached_method == model):
            analysis = {key: cached[key] for key in ("summary", "sections", "method") if key in cached}
            reused += 1
        else:
            pdf_path = PUBLIC_DIR / public_path.lstrip("/")
            text_sections = extract_sections(pdf_path)
            analysis = local_analysis([dict(section) for section in text_sections])
            if use_llm and text_sections:
                try:
                    llm = llm_analysis(text_sections, os.environ["OPENAI_API_KEY"], model, base_url)
                    if llm.get("summary") and llm.get("sections"):
                        analysis["summary"] = llm["summary"]
                        analysis["method"] = model
                except RuntimeError as error:
                    print(f"Aviso: {file_name}: {error}; mantendo resumo extrativo.")
        category = analysis_category(office)
        grouped_results.setdefault((category, state_code), []).append({
            "candidate_id": candidate_id,
            "state_code": state_code,
            "office": office,
            "candidate_type": category,
            "file_name": file_name,
            "public_path": public_path,
            "sha256": expected_hash,
            **analysis,
        })

    topics = [{"id": topic["id"], "label": topic["label"]} for topic in TOPICS]
    index = {
        "analysis_version": ANALYSIS_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "source": "TSE, Dados Abertos; resumos gerados e armazenados por hash do PDF.",
        "summary_policy": "Análises são pré-computadas no workflow e servidas como JSON estático; requisições de visitantes não chamam modelos de IA.",
        "topics": topics,
        "partitions": {},
    }
    generated_paths: set[Path] = set()
    for (category, state_code), grouped_documents in sorted(grouped_results.items()):
        relative_path = Path(category) / f"{state_code}.json"
        output_path = ANALYSIS_DIR / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shard = {
            "analysis_version": ANALYSIS_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "candidate_type": category,
            "state_code": state_code,
            "topics": topics,
            "documents": grouped_documents,
        }
        output_path.write_text(json.dumps(shard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        generated_paths.add(output_path)
        index["partitions"].setdefault(category, {})[state_code] = {
            "path": f"/data/plan-analysis/{category}/{state_code}.json",
            "documents": len(grouped_documents),
        }

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    index_path = ANALYSIS_DIR / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generated_paths.add(index_path)
    for stale_path in ANALYSIS_DIR.rglob("*.json"):
        if stale_path not in generated_paths:
            stale_path.unlink()
    if ANALYSIS_FILE.exists():
        ANALYSIS_FILE.unlink()
    print(f"Análises de plano: {sum(map(len, grouped_results.values()))}; partições: {len(grouped_results)}; reutilizadas pelo hash: {reused}; geradas/reprocessadas: {sum(map(len, grouped_results.values())) - reused}; LLM: {'ativado' if use_llm else 'desativado'}")


if __name__ == "__main__":
    main()

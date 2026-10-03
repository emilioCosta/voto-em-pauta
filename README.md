## Voto em pauta

Aplicação estática Next.js para consultar candidaturas das Eleições Gerais de 2026. A busca funciona no navegador com SQLite em WebAssembly; não há servidor SSR em produção.

### Desenvolvimento local

Requisitos: Node.js 22.13 ou superior e Python 3.12.

```powershell
npm ci
python scripts/rebuild_db.py --public-only
python scripts/build_public_data.py
npm run dev
```

Abra `http://localhost:3000`.

### GitHub Pages

O workflow `.github/workflows/tse-pages.yml` baixa os conjuntos públicos do TSE toda segunda e quinta-feira, gera o snapshot SQLite público, atualiza PDFs e fotos de propostas e publica a versão estática no GitHub Pages. Também pode ser executado manualmente pela aba Actions.

O repositório mantém `public/data/voto_em_pauta.sqlite3`, retratos em `public/fotos/` e propostas em `public/propostas/`. O banco publicado contém candidaturas, histórico eleitoral, declarações de bens com tipo/valor, fotos vinculadas por ID+UF, e referências aos planos; **descrições livres de bens (que podem conter endereços), CPF, e-mails, telefones, títulos eleitorais, prestações de contas e tabelas processuais são excluídos**. Os ZIPs brutos permanecem em `data/`, ignorados pelo Git. Retratos e propostas são os arquivos oficiais correspondentes à candidatura no conjunto CC BY do TSE.

Resumos e tópicos ficam em `public/data/plan-analysis/{tipo}/{UF}.json`, com um `index.json` de partições. Cada plano executivo tem as mesmas 16 seções temáticas; no topo há um resumo geral em texto corrido, e cada seção mostra síntese extrativa e trechos com páginas, sem repetir os títulos internos do PDF. Categorias sem evidência dizem “Não foi observado no plano.” A página baixa apenas o arquivo correspondente ao cargo e estado da candidatura aberta. O workflow usa `scripts/analyze_plans.py` e PyMuPDF: calcula SHA-256 por PDF, reutiliza resultados já versionados quando o conteúdo/versão do algoritmo não mudou e só reprocessa PDFs novos/alterados. Visitantes nunca fazem chamadas a IA.

O TSE registra plano formal de governo para cargos do Executivo, mas não mantém um plano de governo padronizado para cada deputado/senador. Para candidaturas legislativas, fontes sugeridas e as APIs de histórico, proposições e votos da Câmara/Senado estão documentadas em [RESEARCH_SOURCES.md](RESEARCH_SOURCES.md). Programa partidário deve ser identificado como posição do partido, separado de propostas individuais.

Para o Senado, `scripts/collect_senator_proposals.py` verifica apenas sites/documentos vinculados pelo próprio candidato no recurso de redes sociais do TSE. Trechos explícitos são pré-computados em `public/data/senator-proposals/{UF}.json` com URL, data e hash de origem. Cada perfil tem as mesmas 16 seções temáticas, com síntese extrativa e trechos citados; quando nada foi observado numa categoria, a seção diz isso explicitamente. Perfis de redes sociais, páginas partidárias compartilhadas e histórico de mandato não são tratados como propostas individuais. Os status de site indisponível ou fonte não localizada descrevem os limites da coleta, não afirmam que o candidato não tenha propostas.

Os dados e propostas são atribuídos ao Tribunal Superior Eleitoral: [Dados Abertos do TSE - Candidatos 2026](https://dadosabertos.tse.jus.br/dataset/candidatos-2026), licença CC BY. A origem, a licença e os campos excluídos também ficam registrados em `public/data/source-info.json`.

O Pages serve SQLite e PDFs como arquivos públicos, não como banco privado. O navegador de cada visitante baixa a base SQLite para pesquisar. O site exportado deve permanecer abaixo do limite de 1 GB do GitHub Pages; as propostas atuais somam cerca de 295 MB.

### Checagens

```powershell
npm run lint
npm run typecheck
$env:NEXT_OUTPUT_EXPORT = "1"
$env:NEXT_PUBLIC_BASE_PATH = "/voto-em-pauta"
npm run build
npm run preview:pages
```

O preview local fica em `http://localhost:4173/voto-em-pauta/`.


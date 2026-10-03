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

O workflow `.github/workflows/tse-pages.yml` baixa os conjuntos públicos do TSE toda segunda e quinta-feira, gera o snapshot SQLite público, atualiza os PDFs de propostas e publica a versão estática no GitHub Pages. Também pode ser executado manualmente pela aba Actions.

O repositório mantém `public/data/voto_em_pauta.sqlite3` e os documentos de propostas em `public/propostas/`. O banco publicado contém candidaturas, histórico eleitoral e declarações de bens com tipo/valor; **descrições livres de bens (que podem conter endereços), CPF, e-mails, telefones, títulos eleitorais, prestações de contas e tabelas processuais são excluídos**. Os ZIPs brutos permanecem em `data/`, ignorados pelo Git. Os PDFs são escolhidos por candidatura e mantidos como cópias públicas para consulta.

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


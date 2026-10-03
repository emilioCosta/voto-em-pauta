# Fontes, planos e análise de propostas

## Fotos de candidaturas

O conjunto [Candidatos 2026 do TSE](https://dadosabertos.tse.jus.br/dataset/candidatos-2026) publica recursos `UF - Fotos de candidatos`, além de `BR - Fotos de candidatos` para a disputa presidencial. Os ZIPs contêm JPEGs cujos nomes trazem a UF e o identificador `SQ_CANDIDATO` do TSE, por exemplo `FAC10002544107_div.jpg`. O pipeline confere UF e ID contra a candidatura antes de copiar a imagem; arquivos sem correspondência não entram no site. A licença do conjunto é CC BY e a página registra a atribuição à Justiça Eleitoral.

## O que significa “plano” para cada cargo

O TSE recebe a proposta de governo prevista no art. 11, § 1º, IX, da [Lei nº 9.504/1997](https://www.planalto.gov.br/ccivil_03/leis/l9504.htm) para candidaturas do Poder Executivo. O DivulgaCandContas e o conjunto aberto de 2026 são a fonte primária para Presidência e governos estaduais. **Não há no TSE um registro padronizado de plano de governo para candidaturas a senador ou deputado**; não se deve mostrar “sem plano” como descumprimento ou inferir que o parlamentar disputa um programa executivo.

Para candidaturas legislativas, fontes possíveis de compromissos próprios são:

- site oficial de campanha, propostas, entrevistas e debates, guardados com URL, data de publicação/coleta e evidência textual;
- redes/sites informados pelo próprio candidato no cadastro do TSE, respeitando os termos de cada plataforma;
- programa oficial do partido/federação no [TSE - partidos registrados](https://www.tse.jus.br/partidos/partidos-registrados-no-tse/registrados-no-tse). Programa partidário deve aparecer como posição do partido, nunca como compromisso individual atribuído automaticamente ao candidato.

Cada item deve manter `tipo_fonte` (`plano_executivo`, `proposta_individual`, `programa_partidario`, `entrevista`, `debate`), documento/link, data e autoria. Evitar inferir uma proposta de fontes secundárias sem citação direta.

## Passado e atuação parlamentar

Para quem já ocupou mandato, complemente as candidaturas históricas do TSE com os registros da casa legislativa:

- [API Dados Abertos da Câmara](https://dadosabertos.camara.leg.br/swagger/api.html): `/deputados`, `/deputados/{id}/historico`, `/deputados/{id}/mandatosExternos`, `/proposicoes`, `/proposicoes/{id}/autores`, `/proposicoes/{id}/tramitacoes`, `/votacoes` e `/votacoes/{id}/votos`.
- [Dados Abertos do Senado](https://legis.senado.leg.br/dadosabertos/docs/): perfil de senador, mandatos/exercícios, autorias, processos legislativos, discursos e votações nominais. A API é pública, sem autenticação, suporta JSON e documenta limites de requisição e serviços depreciados; prefira os endpoints sucessores do OpenAPI atual.

O TSE e as Casas Legislativas usam IDs diferentes. A associação entre uma candidatura e um parlamentar deve guardar evidência e confiança; não unir apenas por nome quando houver homônimos. Para eleitos em 2026 ainda sem mandato, não inventar histórico legislativo.

## Taxonomia fixa de temas

A análise usa uma taxonomia versionada (`taxonomy_version: 1.0`, algoritmo `analysis_version: 1.6`) e permite múltiplos temas por seção:

1. Educação
2. Saúde
3. Segurança pública
4. Economia e emprego
5. Orçamento e tributos
6. Proteção social
7. Infraestrutura e mobilidade
8. Moradia e saneamento
9. Meio ambiente e clima
10. Agropecuária e desenvolvimento rural
11. Ciência, inovação e digital
12. Cultura, esporte e turismo
13. Direitos e inclusão
14. Gestão pública e transparência
15. Energia e mineração
16. Justiça e defesa

Essa classificação é um índice editorial para navegação, não uma avaliação de qualidade, custo, viabilidade ou ideologia da proposta. Cada tema aponta para o trecho e páginas do PDF de origem; vários temas podem se aplicar à mesma seção.

## Resumos uma única vez por versão

`scripts/analyze_plans.py` extrai texto com `pypdf`, divide por títulos/páginas, classifica cada seção e grava resumo, tópicos, intervalo de páginas, método e SHA-256 em `public/data/plan-analysis.json`. Ao executar novamente, reaproveita a análise de todo PDF cujo hash não mudou. O site estático apenas lê esse JSON: visitas não chamam IA nem consomem tokens.

Por padrão o pipeline gera resumo extrativo (frases retiradas do texto; sem paráfrase nem afirmações novas). Para gerar resumos abstrativos, configure `OPENAI_API_KEY` como secret e `OPENAI_MODEL` como variable do repositório. O workflow então faz uma chamada por PDF novo/alterado e armazena a resposta; a chave não vai para o bundle Pages. Sem segredo, segue com a análise extrativa. Sempre conferir resumos gerados por modelo contra o PDF, pois a síntese pode omitir nuances ou interpretar mal uma promessa.

A análise cobre os PDFs executivos publicados pelo TSE. O método atual não cria planos inexistentes para deputados/senadores. Quando fontes legislativas forem adicionadas, elas devem entrar como documentos separados e usar a mesma taxonomia, com origem e datas próprias.

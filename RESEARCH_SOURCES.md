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

Para candidaturas ao Senado, `scripts/collect_senator_proposals.py` parte dos sites declarados no recurso `Redes sociais de candidatos` do TSE (arquivo oficial: `rede_social_candidato_2026.zip`), mas ignora URLs de redes/plataformas e não atribui páginas compartilhadas sem perfil individual. O coletor respeita `robots.txt`, limita páginas/requisições, guarda trecho literal, título/seção, URL, data, hash e tópicos em `public/data/senator-proposals/{UF}.json`. Uma candidatura sem trecho encontrado recebe um status explícito e os endereços declarados relevantes; isso não significa que ela não tenha propostas fora do material público localizado. Programas partidários e posts de redes ficam fora desta coleta, conforme critério editorial.

Na coleta de 3 de outubro de 2026, os 319 IDs senatoriais ficaram cobertos em 27 arquivos por UF: 37 candidaturas tiveram 173 trechos explícitos em sites/documentos individuais; 50 tinham site acessível sem proposta explícita extraível; 33 tinham site inacessível/bloqueado; 9 apontavam para domínio compartilhado sem perfil individual verificável; 190 não tinham site/documento individual utilizável no cadastro do TSE. São estados de cobertura das fontes pesquisadas, não avaliações sobre existência de propostas na campanha. Cada perfil contém exatamente as 16 categorias da taxonomia, na mesma ordem. A síntese de cada categoria é extrativa, derivada dos trechos citados, sem chamada de IA; quando não há evidência, aparece “Não foi observado no material consultado para esta candidatura.” Dos trechos extraídos, 99 receberam ao menos um tópico; os demais ficam sem etiqueta automática em vez de receber classificação especulativa.

## Passado e atuação parlamentar

Para quem já ocupou mandato, complemente as candidaturas históricas do TSE com os registros da casa legislativa:

- [API Dados Abertos da Câmara](https://dadosabertos.camara.leg.br/swagger/api.html): `/deputados`, `/deputados/{id}/historico`, `/deputados/{id}/mandatosExternos`, `/proposicoes`, `/proposicoes/{id}/autores`, `/proposicoes/{id}/tramitacoes`, `/votacoes` e `/votacoes/{id}/votos`.
- [Dados Abertos do Senado](https://legis.senado.leg.br/dadosabertos/docs/): perfil de senador, mandatos/exercícios, autorias, processos legislativos, discursos e votações nominais. A API é pública, sem autenticação, suporta JSON e documenta limites de requisição e serviços depreciados; prefira os endpoints sucessores do OpenAPI atual.

O TSE e as Casas Legislativas usam IDs diferentes. A associação entre uma candidatura e um parlamentar deve guardar evidência e confiança; não unir apenas por nome quando houver homônimos. Para eleitos em 2026 ainda sem mandato, não inventar histórico legislativo.

## Taxonomia fixa de temas

A análise usa uma taxonomia versionada (`taxonomy_version: 1.0`, algoritmo `analysis_version: 2.18`). As mesmas 16 categorias aparecem, na mesma ordem, em cada ficha de presidente/governador e em cada perfil de senador. A atribuição exige expressão temática específica na frase ou título de seção; referências isoladas a palavras como “saúde” em listas genéricas não bastam:

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

Essa classificação é um índice editorial para navegação, não uma avaliação de qualidade, custo, viabilidade ou ideologia da proposta. Em PDFs executivos, cada categoria contém uma síntese extrativa, trechos de evidência e páginas do plano; quando não há evidência, aparece “Não foi observado no plano.” Em propostas senatoriais, a síntese e os trechos apontam para a página e URL da fonte individual.

## Resumos uma única vez por versão

`scripts/analyze_plans.py` extrai texto com PyMuPDF e grava em `public/data/plan-analysis/{tipo}/{UF}.json` um conjunto fixo de 16 categorias por documento. O resumo geral é um parágrafo corrido, sem rótulos de categoria; dentro de cada categoria, os excertos não exibem os títulos internos do PDF e mantêm apenas o intervalo de páginas e o texto-fonte. `index.json` lista os arquivos e contagens. A página baixa somente o shard do tipo/UF da candidatura consultada. Ao executar novamente, reutiliza a análise por SHA-256 quando conteúdo e versão do algoritmo não mudaram. O site estático apenas lê os arquivos pré-computados: visitas não chamam IA nem consomem tokens.

Por padrão o pipeline gera resumo extrativo (frases retiradas do texto; sem paráfrase nem afirmações novas). Para gerar resumos abstrativos, configure `OPENAI_API_KEY` como secret e `OPENAI_MODEL` como variable do repositório. O workflow então faz uma chamada por PDF novo/alterado e armazena a resposta; a chave não vai para o bundle Pages. Sem segredo, segue com a análise extrativa. Sempre conferir resumos gerados por modelo contra o PDF, pois a síntese pode omitir nuances ou interpretar mal uma promessa.

A análise cobre os PDFs de proposta publicados pelo TSE. No snapshot consultado, as 14 candidaturas a presidente tinham documento associado; entre 201 candidaturas a governador, 200 tinham PDF. Todas essas propostas recebem as mesmas 16 categorias fixas. A exceção sem PDF é Policial Edjane (SP): o G1 noticiou em [18 de setembro de 2026](https://g1.globo.com/sp/sao-paulo/eleicoes/2026/noticia/2026/09/18/policial-edjane-deixa-corrida-ao-governo-de-sp-apos-tre-indeferir-chapa-por-renuncia-de-vice.ghtml) que ela deixou a disputa após o TRE indeferir a chapa; não atribuímos a ela o plano de outra chapa. Embora o TSE não padronize planos individuais para legisladores, o conjunto contém um PDF de proposta associado à candidatura de Silvia Quezado, deputada estadual no RJ. Esse registro foi mantido em `deputado/RJ.json` como exceção documental do conjunto, sem inferir obrigação ou cobertura equivalente para os demais deputados/senadores. Fontes de campanha e entrevistas só devem entrar como documentos separados, com origem/autoria/data verificadas, não como substitutos automáticos do PDF oficial.

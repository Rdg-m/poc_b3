# Resultados da prova de conceito

Data testada: **04/09/2026**.

## Endpoint confirmado

```text
https://www.b3.com.br/pesquisapregao/download?filelist=<ARQUIVO>
```

Padrões confirmados:

- `SPRD260904.zip`: `BVBG.187.01`, relatório simplificado de derivativos;
- `IN260904.zip`: `BVBG.028.02`, cadastro de instrumentos.

## Observações empíricas

- A resposta HTTP é um ZIP externo contendo outro ZIP de mesmo nome.
- Cada ZIP interno da amostra contém dois snapshots XML.
- O snapshot mais recente do `SPRD` declara a data de negociação
  `2026-09-04` e contém **2.292** elementos `PricRpt`.
- Entre os instrumentos observados estão futuros e opções sobre futuros, como
  `GLDZ26`, `BGIH27` e `CCMU27P007000`.
- O XML selecionado do `SPRD` tem aproximadamente **4,78 MB** descompactado.
- O snapshot mais recente do cadastro `IN` tem aproximadamente **641,9 MB**
  descompactado; portanto, sua leitura deve ser incremental (`iterparse`).
- Uma consulta para sábado, **05/09/2026**, devolveu um ZIP sem arquivos. O
  coletor rejeitou corretamente a carga e retornou código de erro.
- Uma segunda execução para o mesmo arquivo local reutilizou a cópia válida,
  sem novo download.

## Decisão técnica provisória

O endpoint é suficiente para a prova de conceito e para um coletor EOD de
pesquisa. Antes de produção, ainda devemos confirmar a regra semântica para
escolher o snapshot final e implementar monitoramento de alterações de layout.

## Evolução: staging Dolt

- O parser `BVBG.187.01` foi implementado com leitura incremental.
- A chave de negócio definida é `(trade_date, instrument_id)`.
- O lote usa o SHA-256 do XML como identificador determinístico.
- O staging preserva todos os campos observados no XML e a moeda individual de
  cada preço/taxa.
- O teste sobre o arquivo real produziu 2.292 chaves únicas e encontrou a opção
  sobre futuro `CCMU27P007000`.
- A saída de preços é determinística: repetir o parser sobre o mesmo XML produz
  as mesmas linhas e hashes.

## Pipeline operacional concluído

- `run_pipeline.py` é o ponto de entrada único.
- Sem parâmetro de data, procura retroativamente o último arquivo publicado.
- Republicações são detectadas pelo checksum do XML, embora o ZIP externo seja
  recriado pela B3.
- A carga usa o protocolo MySQL, transação, upsert e reconciliação pós-carga.
- O working set Dolt precisa começar limpo e a branch precisa ser a esperada.
- `DOLT_VERIFY_CONSTRAINTS` é verificado antes de `DOLT_COMMIT --skip-empty`.
- A integração real com o banco ficou reservada ao ambiente local que possui as
  credenciais; download, parsing e dry-run foram validados integralmente.

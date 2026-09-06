# Contexto e decisões do projeto

## Objetivo

Extrair diariamente dados EOD de futuros e opções sobre futuros da B3, limpar,
validar e disponibilizar os dados para pesquisa quantitativa.

## Banco definido

- **Mecanismo:** Dolt.
- **Consulta e integração:** protocolo compatível com MySQL.
- **Remoto e colaboração:** DoltHub.
- **Unidade de versionamento:** uma carga validada por pregão deve produzir um
  commit Dolt identificável pela data e pelo arquivo-fonte.
- **Reprocessamentos:** devem atualizar a mesma chave de negócio e gerar um novo
  commit, de forma que a correção seja auditável via diff.
- **Execução padrão:** descobrir automaticamente o pregão mais recente
  efetivamente publicado, sem exigir parâmetro de data.
- **Idempotência:** repetir a mesma fonte não deve criar commit vazio; uma
  republicação deve ser detectada pelo hash do XML.

## Fonte inicial

- `BVBG.187.01` (`SPRD`): preços diários consolidados de derivativos.
- `BVBG.028.02` (`IN`): cadastro de instrumentos, a ser incorporado na etapa
  seguinte.

## Chave de negócio inicial

```text
(trade_date, instrument_id)
```

O ticker não é usado como chave porque códigos podem ser reutilizados ou sofrer
alterações. O identificador B3 do instrumento é preservado como texto para não
impor semântica numérica indevida.

## Pipeline operacional

O ponto de entrada único é `run_pipeline.py`. As credenciais permanecem apenas
no `.env` local do usuário. O pipeline deve abortar quando encontrar working set
Dolt previamente sujo, branch inesperada, queda anormal de registros, chaves
duplicadas, data divergente ou violação de constraints.

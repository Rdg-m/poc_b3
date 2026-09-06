# Pipeline EOD B3 → Dolt

Pipeline único para baixar, validar, transformar e versionar o relatório diário
de futuros e opções sobre futuros da B3 (`SPRD` / `BVBG.187.01`). O destino é
uma instância **Dolt**, acessada pelo protocolo MySQL e opcionalmente
sincronizada com o DoltHub.

## O que acontece em cada execução

1. Usa a data atual de `America/Sao_Paulo` como ponto de partida.
2. Consulta até dez datas retroativamente e escolhe o primeiro `SPRD` válido.
3. Atualiza o arquivo bruto mesmo quando já existe localmente, detectando
   republicações da B3 pelo checksum do XML.
4. Valida ZIP externo, ZIP interno, tipo `BVBG.187.01`, data e chaves; entre
   snapshots, escolhe o maior `CreDtAndTm` declarado dentro do XML.
5. Gera TSV determinístico e metadados de linhagem.
6. Verifica que a branch Dolt está correta e que o working set começou limpo.
7. Aplica o DDL, faz upsert e remove registros obsoletos daquela data.
8. Reconcilia contagem, unicidade, lote e constraints.
9. Cria um commit Dolt somente quando o estado final mudou.

## Instalação

Requer Python 3.10 ou superior.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Preencha `.env` localmente. O arquivo é ignorado pelo Git e não deve ser
compartilhado ou incluído no pacote.

## Execução normal

```bash
python run_pipeline.py
```

Não é necessário informar uma data: o pipeline encontra o último pregão
publicado. Para testar download, parsing e guardrails sem conectar ao Dolt:

```bash
python run_pipeline.py --dry-run
```

Para reprocessar uma data explícita:

```bash
python run_pipeline.py --date 2026-09-04
```

Por padrão, a B3 é consultada novamente para detectar revisões. Use
`--reuse-download` somente quando quiser trabalhar offline com uma cópia já
validada.

## Configuração

| Variável | Obrigatória | Padrão | Finalidade |
|---|---:|---|---|
| `DOLT_HOST` | sim | — | host MySQL do Dolt |
| `DOLT_PORT` | não | `3306` | porta |
| `DOLT_DATABASE` | sim | — | banco selecionado |
| `DOLT_USER` | sim | — | usuário exclusivo do pipeline |
| `DOLT_PASSWORD` | sim | — | senha |
| `DOLT_BRANCH` | não | `main` | branch que deve estar ativa |
| `DOLT_SSL_MODE` | não | `REQUIRED` | `DISABLED`, `REQUIRED` ou `VERIFY_IDENTITY` |
| `DOLT_SSL_CA` | condicional | — | certificado CA |
| `DOLT_COMMIT_AUTHOR` | não | usuário SQL | autor `Nome <email>` |
| `B3_MIN_ROWS` | não | `1000` | mínimo absoluto de linhas |
| `B3_MIN_PRIOR_RATIO` | não | `0.50` | razão mínima contra o pregão anterior |

Para Dolt local sem TLS, use `DOLT_SSL_MODE=DISABLED`. Para servidor remoto,
prefira `VERIFY_IDENTITY` com `DOLT_SSL_CA` configurado.

## Idempotência

- `batch_id` é o SHA-256 do snapshot XML selecionado.
- `row_sha256` representa somente os campos de negócio.
- A chave do preço é `(trade_date, instrument_id)`.
- Repetir o mesmo XML produz exatamente o mesmo TSV.
- O ZIP externo não define identidade, pois a B3 o recria a cada requisição.
- `DOLT_COMMIT --skip-empty` evita commits vazios.
- Uma republicação gera novo lote e commit apenas se alterar a linhagem ou os
  dados persistidos.

## Guardrails

- lock local contra duas execuções simultâneas;
- falhas de rede não são confundidas com dia sem pregão;
- busca retroativa limitada a 31 dias;
- arquivo vazio ou com estrutura inesperada é rejeitado;
- data interna deve coincidir com a data solicitada e não pode ser futura;
- contagem mínima absoluta e relativa ao pregão anterior;
- nenhuma chave duplicada no XML/TSV;
- destino precisa responder como Dolt;
- branch divergente aborta a carga;
- working set previamente sujo aborta a carga, evitando commit de alterações
  alheias;
- transação revertida em falhas anteriores ao commit Dolt;
- constraints e contagens são verificadas antes do commit.

## Saídas locais

```text
data/
  raw/YYYY/MM/DD/
    SPRDAAMMDD.zip
    SPRDAAMMDD.zip.metadata.json
  staging/YYYY-MM-DD/
    b3_ingestion_batch.tsv
    stg_b3_derivatives_price.tsv
    manifest.json
    pipeline_result.json
```

## Testes

```bash
python -m unittest discover -s tests -v
python run_pipeline.py --dry-run
```

O teste integral contra o banco deverá ser executado na máquina que contém a
instância e as credenciais Dolt.

## Escopo ainda não incluído

- enriquecimento pelo cadastro `BVBG.028.02`;
- envio automático ao remoto DoltHub;
- agendamento via cron/systemd;
- tabela curada posterior ao staging.

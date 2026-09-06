-- Staging do BVBG.187.01 para Dolt / protocolo MySQL.
-- Execute no banco Dolt que receberá os dados da B3.

CREATE TABLE IF NOT EXISTS b3_ingestion_batch (
    batch_id                  CHAR(64) NOT NULL,
    dataset                   VARCHAR(16) NOT NULL,
    business_file_type        VARCHAR(32) NOT NULL,
    business_group_id         VARCHAR(64) NULL,
    reference_date            DATE NOT NULL,
    xml_created_at            DATETIME(6) NULL,
    source_outer_filename     VARCHAR(255) NOT NULL,
    source_inner_filename     VARCHAR(255) NOT NULL,
    source_xml_filename       VARCHAR(255) NOT NULL,
    source_outer_sha256       CHAR(64) NOT NULL,
    source_xml_sha256         CHAR(64) NOT NULL,
    snapshot_count            INT UNSIGNED NOT NULL,
    row_count                 INT UNSIGNED NOT NULL,
    parser_version            VARCHAR(32) NOT NULL,
    ingested_at_utc           DATETIME(6) NOT NULL,
    PRIMARY KEY (batch_id),
    KEY idx_b3_batch_reference (dataset, reference_date),
    UNIQUE KEY uq_b3_batch_xml (dataset, source_xml_sha256)
);

CREATE TABLE IF NOT EXISTS stg_b3_derivatives_price (
    trade_date                DATE NOT NULL,
    instrument_id             VARCHAR(32) NOT NULL,
    ticker_symbol             VARCHAR(64) NOT NULL,
    instrument_id_type        VARCHAR(16) NULL,
    market_identifier_code    VARCHAR(16) NULL,

    open_interest             BIGINT UNSIGNED NULL,
    first_price               DECIMAL(30,12) NULL,
    first_price_currency      CHAR(3) NULL,
    minimum_price             DECIMAL(30,12) NULL,
    minimum_price_currency    CHAR(3) NULL,
    maximum_price             DECIMAL(30,12) NULL,
    maximum_price_currency    CHAR(3) NULL,
    average_price             DECIMAL(30,12) NULL,
    average_price_currency    CHAR(3) NULL,
    last_price                DECIMAL(30,12) NULL,
    last_price_currency       CHAR(3) NULL,
    regular_transactions_qty  BIGINT UNSIGNED NULL,

    adjusted_quote            DECIMAL(30,12) NULL,
    adjusted_quote_currency   CHAR(3) NULL,
    adjusted_quote_status     VARCHAR(8) NULL,
    adjusted_quote_tax        DECIMAL(30,12) NULL,
    adjusted_quote_tax_ccy    CHAR(3) NULL,
    previous_adjusted_quote   DECIMAL(30,12) NULL,
    previous_adj_quote_ccy    CHAR(3) NULL,
    previous_adj_quote_status VARCHAR(8) NULL,
    previous_adj_quote_tax    DECIMAL(30,12) NULL,
    previous_adj_quote_tax_ccy CHAR(3) NULL,

    batch_id                  CHAR(64) NOT NULL,
    row_sha256                CHAR(64) NOT NULL,

    PRIMARY KEY (trade_date, instrument_id),
    KEY idx_stg_b3_deriv_ticker_date (ticker_symbol, trade_date),
    KEY idx_stg_b3_deriv_batch (batch_id),
    CONSTRAINT fk_stg_b3_deriv_batch
        FOREIGN KEY (batch_id) REFERENCES b3_ingestion_batch (batch_id)
);

# Airbnb Analytics Pipeline

**Metadata-Driven ELT Pipeline — dbt on Snowflake**

`Analytics Engineering` · `ELT` · `dbt` · `Snowflake` · `AWS S3` · `Medallion Architecture` · `Dimensional Modeling` · `SCD Type 2` · `Incremental Models` · `Jinja` · `SQL` · `Python`

An analytics engineering pipeline transforming raw Airbnb listings, hosts, and bookings into analytics-ready fact tables and full-history dimensions, implemented on a Bronze–Silver–Gold medallion architecture in Snowflake.

The Gold layer is generated rather than hand-written: join graphs are declared as configuration and compiled into SQL by Jinja at build time, so extending the warehouse is a configuration change rather than a SQL rewrite.

<br>

![dbt](https://img.shields.io/badge/dbt-1.12-FF694B?style=flat-square)
![Snowflake](https://img.shields.io/badge/Snowflake-Cloud_DW-29B5E8?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square)
![AWS](https://img.shields.io/badge/AWS-S3-FF9900?style=flat-square)

---

## Contents

[Highlights](#highlights) · [Architecture](#architecture) · [Metadata-Driven Design](#metadata-driven-design) · [Incremental Layers](#incremental-layers) · [Gold Dimensional Layer](#gold-dimensional-layer) · [SCD Type 2 Snapshots](#scd-type-2-snapshots) · [Project Structure](#project-structure) · [Setup](#setup) · [Usage](#usage) · [Roadmap](#roadmap)

---

## Highlights

| Capability | Implementation |
|---|---|
| **Metadata-driven pipeline** | Join graphs declared as configuration dictionaries, not hand-written SQL |
| **Dynamic model generation** | Jinja loops compile the OBT and fact table from a single source of truth |
| **Incremental Bronze & Silver** | Two distinct strategies — watermark ingest and merge-on-key — matched to two data profiles |
| **Gold dimensional layer** | Denormalized OBT for BI access, conformed fact table for star-schema analytics |
| **SCD Type 2 history** | Timestamp-strategy snapshots preserving every version of every dimension record |
| **Zero-cost intermediates** | Ephemeral models compile as CTEs, decoupling the history layer without materializing storage |

---

## Architecture

```
CSV sources
     │
     ▼
AWS S3  ──── COPY INTO via Snowflake external stage
     │
     ▼
AIRBNB.STAGING                raw landed tables (outside dbt)
     │
     ▼
AIRBNB.BRONZE                 incremental · watermark filter · append-only
     │
     ▼
AIRBNB.SILVER                 incremental · merge on business key
     │                        macro-driven business logic
     ▼
AIRBNB.GOLD.OBT               Jinja-generated denormalized table
     │
     ├──► ephemeral models ──► SCD2 snapshots ──► DIM_LISTINGS
     │    (compile as CTEs)                       DIM_HOSTS
     │                                            DIM_BOOKINGS
     ▼                                                 │
AIRBNB.GOLD.FACT ◄─────────────────────────────────────┘
```

Ingestion into `AIRBNB.STAGING` runs outside dbt via Snowflake external stages. dbt owns every transformation from Bronze onward, and the full dependency graph resolves through `ref()` — a single `dbt build` executes the entire pipeline in correct order.

### Stack

| Component | Technology |
|---|---|
| Cloud data warehouse | Snowflake |
| Transformation | dbt Core `>=1.12.2` · `dbt-snowflake >=1.12.0` |
| Object storage | AWS S3 |
| Runtime | Python `>=3.12` |
| Dependency management | `uv` |

---

## Metadata-Driven Design

Wide denormalized models are a known maintenance failure point. Each additional dimension means another hand-edited projection and another hand-edited join, and the two drift apart until the table can no longer be trusted.

This pipeline treats the join graph as data. Every participating table is a dictionary declaring its identity, column contribution, and join predicate:

```jinja
{% set configs = [
    {
        'table'   : ref('silver_bookings'),
        'columns' : 'silver_bookings.*',
        'alias'   : 'silver_bookings'
    },
    {
        'table'   : ref('silver_listings'),
        'columns' : 'silver_listings.property_type, silver_listings.city,
                     silver_listings.price_per_night, silver_listings.price_per_night_tag',
        'alias'   : 'silver_listings',
        'join_condition': 'silver_bookings.listing_id = silver_listings.listing_id'
    },
    {
        'table'   : ref('silver_hosts'),
        'columns' : 'silver_hosts.host_name, silver_hosts.is_superhost,
                     silver_hosts.response_rate_quality',
        'alias'   : 'silver_hosts',
        'join_condition': 'silver_listings.host_id = silver_hosts.host_id'
    }
] %}
```

Two Jinja loops compile this into SQL — one projecting columns, one assembling the `FROM` clause:

```jinja
select
    {% for config in configs %}
        {{ config.columns }}{% if not loop.last %}, {% endif %}
    {% endfor %}
from
    {% for config in configs %}
        {% if loop.first %}
            {{ config['table'] }} as {{ config['alias'] }}
        {% else %}
            left join {{ config['table'] }} as {{ config['alias'] }}
                on {{ config['join_condition'] }}
        {% endif %}
    {% endfor %}
```

`loop.first` distinguishes the anchor table from joined tables; `loop.last` handles comma placement. Because the projection and the join graph are generated from one structure, they cannot desynchronize.

![Jinja configuration compiled into SQL](docs/images/split_view.png)

*Right: the join graph declared as configuration. Left: the same configuration compiled into a complete three-table join — no Jinja remains. Using `ref()` rather than literal table names means dbt resolves the full dependency graph automatically.*

`fact.sql` applies the identical pattern against the Gold layer. Onboarding an additional source is one appended dictionary — the generation logic never changes, and maintenance cost stops scaling with table width.

---

## Incremental Layers

Bronze and Silver use deliberately different incremental strategies because they carry different workloads.

### Bronze — watermark ingest

Append-only, no merge key, no comparison overhead. The watermark column is parameterized so the pattern is uniform across all three models:

```jinja
{{ config(materialized='incremental') }}

{% set incremental_col = 'created_at' %}

select * from {{ source('staging', 'listings') }}

{% if is_incremental() %}
where {{ incremental_col }} > (
    select coalesce(max({{ incremental_col }}), '1900-01-01')
    from {{ this }}
)
{% endif %}
```

`coalesce` guards the first run, when `max()` over an empty table returns null. Bronze remains an immutable in-warehouse record of what landed.

### Silver — merge on business key

Silver is where records change: hosts update response rates, listings change price. Because Bronze is append-only, it can hold several versions of the same record — so Silver deduplicates to current state before merging on its business key:

```jinja
{{ config(materialized='incremental', unique_key='listing_id') }}

select
    listing_id,
    host_id,
    property_type,
    city,
    price_per_night,
    {{ tag('price_per_night') }} as price_per_night_tag,
    created_at
from {{ ref('bronze_listings') }}
qualify row_number() over (partition by listing_id order by created_at desc) = 1
```

`qualify` filters after the window function evaluates, collapsing each business key to its most recent version. Without it, a merge against multiple source rows for one target key fails outright.

| Layer | Strategy | Merge key | Rationale |
|---|---|---|---|
| Bronze | Watermark filter | — | Cheap, high-volume, immutable ingest |
| Silver | Merge + dedupe | Business key | Upstream records mutate; collapses to current state |

Business logic is centralized in macros rather than inline `CASE` blocks, giving each rule a single definition:

| Macro | Purpose |
|---|---|
| `tag()` | Bands `price_per_night` into `low` / `medium` / `high` |
| `multiply()` | Derives `total_amount` from nights booked and booking amount |
| `trimmer()` | String normalization |
| `generate_schema_name()` | Overrides dbt's default schema prefixing |

The schema override strips dbt's default prefix so layers land in clean namespaces — `AIRBNB.BRONZE`, `AIRBNB.SILVER`, `AIRBNB.GOLD` — rather than `dbt_schema_bronze`.

---

## Gold Dimensional Layer

Gold serves two consumption patterns from one Silver foundation.

**`obt` — One Big Table.** Fully denormalized bookings ⋈ listings ⋈ hosts. Single-table access for BI tools and ad-hoc analysis, requiring no join literacy from consumers.

![OBT sample rows](docs/images/OBT_sample_rows.png)

*Booking, listing, and host attributes resolved onto a single row.*

**`fact` — conformed fact table.** Measures (`total_amount`, `service_fee`, `cleaning_fee`, `price_per_night`, `response_rate`) plus foreign keys to the SCD2 dimensions. Dimension joins are restricted to currently-valid records so historical versions don't multiply fact rows:

```jinja
'join_condition' : "gold_obt.listing_id = dim_listings.listing_id
                    and dim_listings.dbt_valid_to = to_date('9999-12-31')"
```

**Ephemeral staging models.** Three models slice the OBT into entity-scoped column sets and feed the snapshot layer. Because OBT sits at booking grain, models targeting a coarser grain deduplicate before the snapshot merge. They compile inline as CTEs and never materialize in Snowflake — no storage cost, no maintenance surface.

---

## SCD Type 2 Snapshots

Dimensions change. A host loses superhost status; a listing is recategorized. Overwriting destroys the ability to answer *what did this record look like when the booking occurred?*

Three timestamp-strategy snapshots capture every version of every dimension record:

```yaml
snapshots:
  - name: dim_listings
    relation: ref('listings')
    config:
      database: airbnb
      schema: gold
      unique_key: listing_id
      strategy: timestamp
      updated_at: listings_created_at
      dbt_valid_to_current: "to_date('9999-12-31')"
```

| Snapshot | Unique key | Change detection |
|---|---|---|
| `dim_listings` | `listing_id` | `listings_created_at` |
| `dim_hosts` | `host_id` | `host_created_at` |
| `dim_bookings` | `booking_id` | `created_at` |

dbt maintains `dbt_valid_from` and `dbt_valid_to` automatically. Setting `dbt_valid_to_current` to `9999-12-31` rather than leaving open records `NULL` means point-in-time queries need no null-handling branch:

```sql
select *
from airbnb.gold.dim_listings
where '2026-03-15' between dbt_valid_from and dbt_valid_to;
```

### Verified change tracking

A price change on a single listing, traced end to end through the pipeline:

![SCD Type 2 version history](docs/images/SCD.png)

*Listing 31 after a price reduction. The prior version (`high`) closes at the exact instant the new version (`low`) opens — no gap, no overlap — and the current record carries the `9999-12-31` sentinel.*

---

## Project Structure

```
AIRBNB-DBT-SNOWFLAKE-AWS/
├── pyproject.toml
├── uv.lock
├── src/dbt_snowflake/
│
└── aws_dbt_snowflake_project/
    ├── dbt_project.yml                 layer materialization + schema config
    │
    ├── models/
    │   ├── sources/sources.yml
    │   ├── bronze/                     bronze_bookings · bronze_hosts · bronze_listings
    │   ├── silver/                     silver_bookings · silver_hosts · silver_listings
    │   └── gold/
    │       ├── obt.sql                 metadata-driven denormalized table
    │       ├── fact.sql                conformed fact table
    │       └── ephemeral/              bookings · hosts · listings
    │
    ├── macros/                         generate_schema_name · tag · multiply · trimmer
    ├── snapshots/                      dim_bookings · dim_hosts · dim_listings
    ├── tests/                          source-boundary assertions
    ├── analyses/                       exploration + Jinja pattern reference
    └── seeds/
```

---

## Setup

**Prerequisites:** Snowflake account with `ACCOUNTADMIN` or equivalent · Python 3.12+ · AWS account with an S3 bucket to replicate ingestion.

**1. Clone and install**

```bash
git clone https://github.com/nazishatta/AIRBNB-DBT-SNOWFLAKE-AWS.git
cd AIRBNB-DBT-SNOWFLAKE-AWS
uv sync
```

**2. Provision Snowflake**

Create the `AIRBNB` database and `STAGING` schema, then land the three source tables — `LISTINGS`, `HOSTS`, `BOOKINGS` — via `COPY INTO` from an S3 external stage or direct upload.

**3. Configure the dbt profile**

Create `~/.dbt/profiles.yml`:

```yaml
aws_dbt_snowflake_project:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: <account-identifier>
      user: <username>
      password: "{{ env_var('SNOWFLAKE_PASSWORD') }}"
      role: ACCOUNTADMIN
      database: AIRBNB
      warehouse: COMPUTE_WH
      schema: dbt_schema
      threads: 4
```

Credentials are never committed. Use `env_var()` or key-pair authentication.

**4. Verify**

```bash
cd aws_dbt_snowflake_project
dbt debug
```

---

## Usage

```bash
dbt build                         # models + tests + snapshots, dependency-ordered
```

A single `dbt build` executes the full pipeline — Bronze → Silver → OBT → snapshots → fact — in dependency order, because every cross-layer reference resolves through `ref()`.

Individual stages:

```bash
dbt run                           # build all models
dbt snapshot                      # capture SCD2 history
dbt test                          # run data quality assertions
```

Selective execution:

```bash
dbt run --select bronze                # a single layer
dbt run --select silver_listings+      # a model and everything downstream
dbt run --full-refresh                 # rebuild incrementals from scratch
```

Documentation and lineage:

```bash
dbt docs generate && dbt docs serve
```

### Data Quality

Source-boundary assertions validate booking amounts before transformation, configured at `warn` severity so anomalies surface without blocking the build. SCD2 snapshots enable reconciliation of any dimension record at any point in time, and dbt's DAG surfaces upstream dependencies and downstream blast radius for every model.

---

## Roadmap

- [ ] Generic schema tests (`unique`, `not_null`, `accepted_values`, `relationships`) and model descriptions via `schema.yml`
- [ ] Extend `qualify` deduplication to the host and booking ephemeral models
- [ ] Terraform-managed S3 stage and Snowflake storage integration
- [ ] CI/CD via GitHub Actions — `dbt build` on pull request against a CI target
- [ ] dbt exposures mapping models to downstream BI dashboards
- [ ] Column-level masking policies on host PII
- [ ] Source freshness checks and pipeline alerting

---

## Author

**Nazish Atta**
MS Data Science — George Washington University

Analytics Engineering · Data Pipelines · Snowflake · dbt · Python · SQL · AWS

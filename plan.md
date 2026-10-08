# P1: Air-quality comparison platform

This is the complete plan for P1. A new chat needs only this file.

- **Part 1** is the plan in plain language: what the project is, what gets built, in what order, and what is still open.
- **Part 2** is the reference to use while building: the exact rules, the checks to run first, and the facts already verified.

Status: plan only. Nothing is built.

---

# Part 1: The plan

## Why this project exists
What the project must be:
- A real-world problem with a user who would care about the answer.
- A platform, not single-dataset practice: new datasets plug in, and the output is a comparison someone can use.
- Something visible to show: a dashboard and a one-command demo.
- Public data only, at near-zero cost. Nothing from my employer or my thesis goes into it.

There is no deadline. The project is built in stages, and every stage ends with something that runs and can be shown.

The lakehouse setup and the agent-tool pattern should stay easy to reuse in later projects.

## The problem
Air-quality and weather measurements come from regulatory monitors, cheap citizen sensors and atmospheric models. They disagree with each other, use different names, formats, units and time conventions, have gaps, and get re-issued later with changes. City analysts, public-health staff and journalists need one trustworthy table, and a way to see what data exists, before they can compare anything.

## Parameters
A parameter is one kind of measurement. The platform starts with PM2.5 (fine dust), then adds temperature and humidity. It is built so that a further parameter is added by describing it, not by rewriting the models.

Humidity matters for a specific reason: cheap sensors tend to read too high in humid air, so it is needed to explain when they disagree with the official monitors.

AQI is not a parameter. It is an index computed from several pollutants with a different formula in each country, so the platform does not ingest it.

## Questions the platform answers
1. For each station and month, on how many days did the daily average PM2.5 exceed the WHO guideline value (15 µg/m³), and is that number higher than in the same month a year earlier?
2. How much do low-cost sensors near a reference monitor disagree with it, and how does that change with humidity and temperature?
3. How well does the model data match what the monitors measured?
4. Which stations and sensors have unhealthy data (gaps, stuck values, late deliveries)?
5. For a given parameter, city and period, which sources and stations have data, how complete is it, and how fresh?

All five are answered for at least two cities, so the output is a comparison.

## How the data flows
1. **Land:** files arrive from the OpenAQ archive, the openSenseMap archive and the Open-Meteo API.
2. **Ingest:** each file is checked against its source's contract, stored as validated or quarantined with a reason, and a pointer records which version of that file is current.
3. **Model:** dbt builds raw, then hourly, then daily, then comparison tables, with tests and contracts at each step.
4. **Gate:** the models are built in a staging area, and only a fully passing build is promoted.
5. **Publish:** each promotion is one transaction, and every published table gets a new Iceberg snapshot in it.
6. **Serve:** DuckDB feeds the dashboard and the agent's read-only tools.

## What I build
1. **A connector framework.** Each source is a plug-in: a short YAML contract (fields, units, time convention, licence, duplicate key, and which of its fields map to which parameter) plus a small adapter. Starting sources are the OpenAQ archive (reference monitors) and the openSenseMap archive (low-cost sensors, including their own temperature and humidity readings).
2. **Ingestion, run by Airflow.** It loads history from 1 January 2025 and adds new days on each run. It can be re-run and backfilled safely. It records which version of each delivered file is current, and quarantines broken files with a reason.
3. **A metadata layer.** This is what lets the platform answer for any parameter and say what data exists:
   - a parameter vocabulary: for each parameter its standard name, unit, valid range, how readings are averaged, and what each source calls it;
   - a registry of stations and sensors;
   - an availability catalog: for each source, station and parameter, the time range covered, how complete it is, how fresh, and its quality;
   - a catalog entry for each source, generated from its contract.

   The vocabulary and registry are dbt seeds and the catalog is a tested dbt model, so the layer is published through the same gate as the data. It is modelled on public standards: OGC SensorThings for stations, sensors and observations, CF names and UCUM units for the vocabulary, and DCAT for the entry per source.
4. **A common model in dbt.** All readings go into one long table with one row per station, parameter and hour. Units, time zones and quality flags are made consistent. Models go from raw, to hourly, to daily, to the comparison tables, with tests and enforced contracts at each step, and a station table that keeps history.
5. **A publish gate.** Models are built and tested in a staging area. Only a fully passing build is promoted to the published tables, and each promotion is one transaction that gives every published table a new Iceberg snapshot, so any earlier release can still be queried or restored.
6. **A lakehouse.** Iceberg tables on RustFS, an S3-compatible object store, through a REST catalog, queried with DuckDB. It includes demos of time travel and schema change, and a measured benchmark of file compaction.
7. **A dashboard.** A station map, exceedance days by month and year, sensor-versus-monitor disagreement against humidity and temperature, data health, and what data exists for each parameter. Every view explains itself: one sentence on what it shows and how to read it, a finding in plain words, and short definitions of its terms.
8. **An agent module.** An MCP server exposes five read-only, typed tools over the published tables, with row limits and an audit log. Each tool takes the parameter as an argument:
   - **find** what data exists for a parameter, place and period;
   - **fetch** the values;
   - **summarise** them (averages, valid days, days above a guideline);
   - **compare** two sources or stations;
   - **trace** a value back to its source file, licence and release.

   A local-model analyst agent must cite tool results and flag stale or low-quality data. It is tested on questions with known answers, on hostile text hidden in a source field, and on out-of-scope requests.
9. **An AWS deployment of the ingestion.** The same ingestion function as S3 to SQS to Lambda to DynamoDB, deployed with Terraform on LocalStack (an AWS emulator).

## Example questions for the agent
- What humidity data do you have for this city in March 2025, and how complete is it?
- On how many days in January 2026 did this station exceed the WHO PM2.5 guideline, and how does that compare with January 2025?
- How far apart were this sensor and its reference monitor last month, and was the gap larger in humid hours?
- Which of the two cities had more days above the guideline this year?
- Which sensors in this city had gaps or stuck values this month?
- Where does this value come from, and under what licence?
- What is the AQI here today? (The agent must explain that AQI is an index computed from several pollutants with a different formula in each country, that the platform does not ingest it, and offer the PM2.5 values instead.)
- Delete the readings for this station. (The agent must refuse: its tools are read-only.)

## Stages
Each stage ends with something that runs and can be shown.

1. **One source and one city, end to end, for PM2.5.** Ingest history from January 2025, model, gate, publish to Iceberg, answer question 1. The vocabulary and the long table are in place from the start, with PM2.5 as the only parameter.
2. **The low-cost source and a second city.** openSenseMap is added with its temperature and humidity readings. Questions 2, 4 and 5, and the dashboard.
3. **A third source onboarded from scratch.** Default: Open-Meteo, for CAMS model PM2.5 and for weather. Answer question 3. Record the time taken, lines of adapter code and lines of config.
4. **The agent module and its tests.**
5. **Lakehouse demos, the compaction benchmark, and the Terraform deployment.**

## Headline demos
- **Gate demo:** publish a good release, deliver a re-issued file that is valid but incomplete, and show that the gate blocks it while the published tables stay unchanged.
- **Onboarding record:** what it took to add the third source.
- **The dashboard** itself, across two cities.
- **Agent test table:** pass counts, including the hostile case.

## Tech
Python, Airflow, dbt, DuckDB, Iceberg, RustFS, Ollama, MCP, Terraform, LocalStack.

## Honest limits
- Results are per station, not per neighborhood.
- Exceedance counts are descriptive, not a statement of WHO compliance.
- The metadata layer is modelled on public standards. It is not a compliant implementation of any of them and serves no standard API.
- Open-Meteo weather values are model estimates for an area, and the sensors' own humidity readings come from low-cost hardware.
- AQI is not provided.
- The data fits on a laptop, so this is not a scale project. The compaction benchmark is the only performance content.
- The onboarding record is one measured exercise, not a general speed claim.
- The AWS part is emulated.

## What the repository must have
- A README with the problem, a diagram, a one-command run, tests in CI, results produced by a script, stated limitations, and one honest failure case.
- Only claims that a passing check proves. An emulated AWS run is described as "LocalStack-emulated", never as "ran on AWS".

## Before building starts
Things only I can do:
- Get an OpenAQ API key.
- Choose two cities where a reference monitor and low-cost sensors sit close together, with data from both since January 2025.
- Create a LocalStack account (free tier, non-commercial) for the Terraform step.

Things the new chat does first:
- Run the checks listed in Part 2. The ones most likely to change the design are: the low-cost source's data licence (Sensor.Community's was unclear, so openSenseMap replaced it on 2026-10-05); whether dbt can write Iceberg tables through DuckDB, which has a fallback; and the standard names and units that go into the vocabulary.
- Then create the repository in this folder and build stage 1.

## Still to decide
**Decided on 2026-10-07: SQLite.** The question was where the pipeline keeps its record of which file version is current. This plan uses SQLite for the everyday pipeline and DynamoDB only in the emulated AWS deployment. The alternative is DynamoDB Local, AWS's free downloadable DynamoDB, for the everyday pipeline too, with LocalStack kept only for the Terraform deployment. That would make DynamoDB's conditional writes everyday code, at the cost of one more container in the everyday stack and in CI. The owner chose SQLite. What was checked about DynamoDB Local is in the facts table in Part 2.

## How I like to work
- Write plans in plain language I can read without knowing earlier drafts.
- Check with me before changing scope. Do not cut features to fit a time budget.
- When asking me to choose, explain the question in everyday terms first: what it is, why it matters, and what each option means.
- Treat outside reviews as input to verify, not as instructions.

---

# Part 2: Reference for building

This part is not meant to be read start to finish. It has three sections: the design rules the build must follow, the checks to run before building, and the facts that were checked against official documentation.

## Design rules

**Parameters (the vocabulary)**
- A parameter is one kind of measurement. The vocabulary is a dbt seed with one row per parameter: canonical name, CF standard name, UCUM unit, valid range, aggregation rule, and guideline value if one exists. Each source's contract maps its own field name and unit string to a parameter.
- The same seed drives the unit check, the models, the dashboard filters and the allowed values of the agent tools, so a parameter cannot exist in one place and not another.

| Parameter | CF standard name | Unit (UCUM) | Valid hourly value | Aggregation | Guideline |
|---|---|---|---|---|---|
| `pm25` | `mass_concentration_of_pm2p5_ambient_aerosol_particles_in_air` | `ug/m3` | 0 to 1000 | mean | WHO 2021 24-hour value: 15 |
| `temperature` | `air_temperature` | `Cel` | -60 to 60 (proposed) | mean | none |
| `relative_humidity` | `relative_humidity` | `%` | 0 to 100 (proposed) | mean | none |

- CF's own units are SI (kg m-3 for mass concentration, K for temperature), which air-quality sources do not use. CF supplies the name only; the stored unit is the UCUM one in the table.
- The two ranges marked proposed are confirmed against real files before coding. The CF and UCUM entries not yet read at the source are listed in the checks below.
- **Adding a parameter** means one seed row and a mapping in each source contract that delivers it, with no model change. This holds for parameters averaged by a plain mean. A parameter that needs another rule (a sum for rainfall, a circular mean for wind direction) is added only after that rule is implemented and tested.
- **AQI is not a parameter.** It is an index computed from several pollutants with a different formula in each country. It is not ingested. If it is ever added, it is a derived metric with its formula stated.

**Metric rules (fixed before coding, in config and README)**
These hold for every parameter. Values that differ by parameter come from the vocabulary.
- **Rows used:** one sensor per station and parameter, pinned by sensor id in the registry. Rows from other sensors, or for parameters not in the vocabulary, are ignored and counted.
- **Units:** the unit string is stripped and normalized with Unicode NFKC (which turns the micro sign `µ` into Greek `μ` and `³` into `3`) and must then equal the parameter's unit or a spelling its source contract lists for it. For PM2.5 that is `μg/m3` or `ug/m3`; OpenAQ's documented example spells it `µg/m³`. Any other unit quarantines the file unless the source's contract declares a conversion.
- **Hours:** OpenAQ timestamps mark the **end** of the period (03:00 means 02:00-02:59). The hour is identified by its start. Each source's contract states its own time convention, and sub-hourly sources are averaged to the hour only if the contract says how.
- **Valid hour:** exactly one distinct value for that sensor-hour, inside the parameter's valid range. Identical duplicate rows keep one; conflicting rows make the hour invalid.
- **Local day:** calendar date of the hour's start in the station's IANA timezone. Days are assigned from timestamps, not from file names. DST days have 23 or 25 hours; coverage uses that day's real hour count.
- **Period:** from 2025-01-01, or the registry's start date for a sensor that began later, to the latest day the source's archive should hold. That end is today minus the source's archive lag, which is measured per source in pre-flight (OpenAQ files were observed four days after the day).
- **Day status:** every station and parameter in the registry has exactly one row for every date in its period, with status `valid` (at least 75% of that day's hours valid), `excluded_low_coverage`, or `excluded_no_file`. Daily value = unrounded mean of valid hours.
- **Exceedance:** defined only for a parameter with a guideline value, which today is PM2.5. Exceed = daily mean strictly greater than the guideline (15 for PM2.5).
- **What the count means:** a descriptive count of days above the WHO 2021 24-hour guideline value. It is not a statement of WHO compliance, because that level is defined against the 99th percentile of a year of daily means.
- **Year over year:** a month is compared with the same month a year earlier only for stations with valid days in both, and the number of valid days behind each figure is shown.
- Known simplification, stated in the README: small negative PM2.5 readings that some monitors report are treated as invalid hours.

**Metadata layer**
- The tables follow the OGC SensorThings data model in structure and naming:

| Platform table | SensorThings entity | Holds |
|---|---|---|
| `station` | Thing with its Location; HistoricalLocation for the history | One monitoring site: source and location ids, coordinates, timezone, provider, licence |
| `sensor` | Sensor | One device at a station: sensor id and type |
| `parameter` (seed) | ObservedProperty | The vocabulary above |
| `datastream` | Datastream | One sensor measuring one parameter at one station in one unit |
| `observation` | Observation | Station, parameter, hour start, value, validity, and the source file version it came from |

  FeatureOfInterest is not modelled: the feature is always the air at the station.
- **Availability catalog:** a dbt model with one row per datastream: first and last valid hour, share of valid hours in the period, hours since the last observation, and counts of invalid hours by reason. It is derived from the observation table in the same build and promoted in the same snapshot, so it cannot disagree with the published data.
- **Entry per source:** a DCAT-style file generated from the source contract (title, publisher, licence, time range, area, update frequency, download location). It is generated, never edited by hand.
- **Sensors at one site:** openSenseMap publishes a box as one folder with one file per sensor, so PM2.5, temperature and humidity each have their own sensor id. The registry joins them by the box id. A sensor's name is typed in by the box's owner, so the registry records which sensor id is which parameter.
- **Wording:** the README says "modelled on" these standards. The platform serves no SensorThings API and makes no conformance claim.

**Comparison rules**
- **Station level only.** A station reading does not establish what a neighborhood experienced, so no neighborhood claims without a stated spatial method.
- **Pairing:** a low-cost sensor is compared with a reference monitor only if they are within about 1 km and share at least 70% of hours over the comparison period. A city is used only if it has at least three such pairs.
- **Disagreement:** computed only on hours valid in both. Report the mean difference and the mean absolute difference per pair, by month, with the number of hours behind each figure.
- **Conditions:** the same two figures are also reported by humidity band and by temperature band. The bands and the minimum number of hours per band are fixed in config before any result is looked at; a band below the minimum is shown as "not enough data". Open-Meteo weather at the monitor's location is the condition value every pair has; the sensor's own humidity is used as a second view where it exists. Each figure states which one it used.
- **Model data:** CAMS values are grid-cell estimates (about 11 km in Europe, 45 km globally), and Open-Meteo weather values are grid-cell estimates too (about 9 to 25 km depending on the model). They are labeled as model output and compared with a station only as "model versus measurement at this point".

**Ingestion contract**
- `ingest(event)` does, in this order: read the object; if its content no longer matches the event (it was overwritten), stop, because a newer event will follow; validate; write the result to `validated/<key>/<content sha256>` or `quarantine/...` (the same input always gives the same path, so a retry overwrites identically); then conditionally move the pointer for that file's key: set `(current_version, sequencer)` only if no pointer exists or the stored sequencer is older.
- A quarantined version never moves the pointer. Readers use only versions the pointer names, so an object written just before a failed pointer update is unreferenced and harmless.
- **File validation is structural only:** the file opens, the header matches the source's contract, there is at least one row, keys and dates match the file's key, and units pass the unit rule. It has no value-range check and no minimum row count: an out-of-range reading or a short day is legitimate input that the models must count, not reject.
- Storage and pointer sit behind two small interfaces, so the same function runs locally (directory and SQLite) and on AWS (S3 and DynamoDB).
- **Backfill:** history from 2025-01-01 is loaded by the same `ingest` function, one file at a time, throttled, and resumable: a file version already validated is skipped by its content hash. The openSenseMap adapter builds one URL form: every day is a folder at the top level of the archive.
- **Source manifest** (committed): source and location ids, sensor ids and their parameters, each unit string exactly as found, provider, timezone, licence and its permissions (redistribution, attribution, commercial use, modification, share-alike), observed spacing between rows, first and last timestamps, dates with no file, file hashes. The history itself is not committed: the repo ships the download script and hashes. A small fixed window of real files is committed as test fixtures only if the licence allows redistribution.

**Publish gate**
- dbt alone is not a gate: it materializes a model before running that model's data tests. So models are built in a **candidate** schema, `dbt build` runs there, and only exit code 0 leads to promotion.
- The candidate is a DuckDB database file outside the Iceberg catalog, the owner's choice of 2026-10-07. Through DuckDB the catalog accepts only incremental models from dbt (check 0.3), and in a DuckDB file every kind of model works. Promotion copies the candidate's tables into the catalog. The raw and hourly tables are incremental in the candidate, the owner's choice of 2026-10-07: a build replaces only the stations and days whose file version changed, so the work does not grow with the history, and a full rebuild stays possible. The daily and later tables are small and are rebuilt in full.
- Promotion writes the published tables, the metadata layer included, in one transaction, and appends a row to a release log (release id, each table's snapshot id, input hashes). Iceberg keeps snapshots per table, and replacing a table's rows makes two, a delete and an insert, so a release is one transaction and not one snapshot (tried by hand on 2026-10-07; task 1.17 tests it). A failed build promotes nothing.
- The published observation table is one table for all sources, partitioned by source and month, the owner's choice of 2026-10-07. A query for one source reads only that source's files, a query for a period reads only those months, and loading one source cannot disturb another's files.
- Two tests carry the gate: every station and parameter has one row for every date in its period, and every station-parameter-day that is valid in the published tables must still be valid in the candidate unless it is listed in an `acknowledged_regressions` seed.
- **Gate demo, fault "truncated re-delivery":** a new version of an already published station-day that is structurally valid but holds 6 of 24 hours. Validation accepts it and the pointer moves; the candidate build fails; the script asserts that the retained-days test is the only failing node, that the published tables' row hashes and the release id are unchanged, and that the agent tool still returns the earlier answer. Delivering the complete file again publishes the next release.
- Unit tests around the gate: duplicate event gives one pointer and one object; a malformed newer version is quarantined and the pointer stays; a stale event replayed later does not move the pointer back; a failure injected between the object write and the pointer update is repaired by a retry; an exception in the middle of promotion leaves the published tables unchanged.
- CI runs the build and the gate tests on the committed fixture window, not on the full history.

**Dashboard**
- Every view carries one sentence saying what it shows and how to read it, a finding in plain words above its chart, and short definitions of the terms it uses (PM2.5, the WHO value, a valid day). A reader who knows nothing about air quality must be able to say what a view means.
- Exceedance days are shown as a share of the valid days, with the count beside it, for example "55%, 17 of 31 days".
- A view that does not apply to the chosen parameter says so. Whether a parameter has a guideline comes from the vocabulary, never from the view's code.
- An answer from the agent can be shown as a new section on the page, a table or a chart drawn from the tool's result. A section can be deleted, lasts for the session, and is kept only if the user chooses to keep it.
- Sources are never averaged together. A figure for a city comes from the reference monitors and says so; low-cost sensors and model data are shown beside it, labelled.

**Onboarding exercise**
- Start from a documented baseline (the framework with two sources working). The third source is Open-Meteo, which has two endpoints: CAMS model PM2.5 and historical weather. Record elapsed time, lines of adapter code, lines of contract and config, and the validation work needed, for each endpoint. Report it as one measured exercise. Make no claim about general onboarding speed.

**Agent module**
- **Tools.** All five are read-only and take the parameter as an argument:

| Tool | Arguments | Returns |
|---|---|---|
| `find_data` | parameter; optional city, source, period | Catalog rows: which datastreams exist, their time range, coverage, freshness and quality |
| `get_observations` | parameter, stations, period, grain (hour or day) | Values with their validity status |
| `summarize` | parameter, stations or city, period, statistic (mean, minimum, maximum, valid days, exceedance days), grouping (station, month) | One row per group, with the number of valid hours or days behind it |
| `compare` | parameter, two datastreams, period; optional condition (humidity or temperature bands) | Mean difference, mean absolute difference and hours, as in the comparison rules |
| `trace` | one observation's station, parameter and hour | Source, file key and content hash, licence and attribution, release id and snapshot id |

- Parameters, stations, statistics and groupings are enumerations taken from the vocabulary and the registry. Invalid arguments are rejected and returned to the model, never run. The model never writes SQL.
- Every result carries the release id and the freshness and coverage of the datastreams it used. The agent must say so when data is stale or coverage is low.
- Each call has a row limit set in config (placeholder 500) and is written to the audit log.
- `summarize` refuses `exceedance days` for a parameter with no guideline value.
- **AQI:** asked for an AQI, the agent explains that it is a derived index with a country-specific formula, that the platform does not ingest it, and offers the PM2.5 values.
- **Tests:** questions with known answers computed by a script from the published tables; hostile text hidden in a source field; out-of-scope requests, the AQI question and a request to change data among them.
- **Claims.** An MCP server is an interface, not an authorization system. The claims are limited to: read-only connection, typed and parameterized tools, row limits, an audit log of every call, and the pass counts on the test questions. One hostile case shows nothing general, and the README says so.

**AWS deployment on LocalStack**
- The ingestion function ships as a Lambda zip package (standard library and boto3, no layers or container images). The S3 notification covers the `landing/` prefix only, so the function cannot trigger itself.
- Tests: deploy; upload one file and get one pointer item and one validated object; deliver the same message again and still have one of each; deliver two versions of one key and replay the older event without the pointer moving back; destroy.
- Passing tests show the wiring deployed and destroyed with Terraform against an emulator. They do not show IAM policy enforcement, state persistence, or real throughput, quotas, cost, latency or networking, none of which the free tier provides.
- Because LocalStack needs a token, CI and every headline result run without it. LocalStack results are committed as logs with the command that produced them.

## Checks to run before building

- OpenAQ API key obtained; the archive downloads without credentials; attribution text recorded per provider.
- Two cities chosen that pass the pairing rule, with the monitor and the paired sensors reporting since January 2025. If none passes, the low-cost comparison is dropped for that city, not weakened.
- Source manifests filled in. A source or station whose licence is missing or unclear is dropped.
- On real files, for each parameter: the header, the exact unit string and the hour convention match what the contract says. If they differ, fix the contract and validator, not the metric rules.
- openSenseMap: the licence read from a primary source; the files of a PM sensor and of a temperature and humidity sensor read from real boxes, including the box id that joins them and how box owners name their sensors; the spacing between readings measured.
- Whether the chosen OpenAQ stations report temperature or humidity.
- The archive lag measured per source, and one station backfilled for one month end to end before the whole period is loaded.
- Vocabulary: the PM2.5 and relative-humidity entries read on the CF standard-name table itself; the UCUM spellings `ug/m3`, `Cel` and `%` checked against the UCUM specification; the proposed valid ranges for temperature and humidity compared with real files.
- The WHO 2021 guideline document opened and the 15 µg/m³ 24-hour value confirmed by eye.
- DuckDB creates an Iceberg table through the REST catalog on RustFS, inserts, and reads an earlier snapshot. RustFS replaced MinIO on 2026-10-06: MinIO's project is archived and its official image is gone. **If it fails:** write with PyIceberg and read with DuckDB.
- dbt-duckdb and DuckDB versions pinned as tested. The local model returns valid tool arguments in at least 8 of 10 trial calls.
- For the Terraform step: a LocalStack account and token on a personal machine, and the Docker socket mounted for Lambda.

## Facts checked against official documentation
Checked on 2026-10-03 unless a row gives a later date. Anything marked unverified is covered by a check in the section above, unless the row says otherwise.

| Claim | Result |
|---|---|
| LocalStack Hobby is non-commercial and includes S3, Lambda, SQS, SNS, DynamoDB, Kinesis Data Streams, Firehose, Step Functions, EventBridge, IAM, CloudWatch, CloudWatch Logs, CloudFormation, Secrets Manager | Confirmed (docs.localstack.cloud/aws/licensing, "as of March 23rd, 2026"). The page states the matrix "does not indicate the level of API coverage or feature availability". |
| Hobby excludes Glue, Athena, Lake Formation, MSK, MWAA, Managed Flink, EMR | Confirmed (same page; ECR and ECS are also excluded) |
| Hobby has no IAM policy enforcement and no local state persistence | Confirmed: both are feature rows of the plan matrix and both are unavailable on Hobby. Note: "Persistence Supported" on the S3 and Kinesis service pages describes what the service can do, not what Hobby includes. Every run deploys from empty. |
| Auth token is mandatory to start the LocalStack container | Confirmed (docs.localstack.cloud/aws/getting-started/auth-token: "a mandatory credential required to start the LocalStack container"); failure text "License activation failed". The page names no plan exemption. |
| Terraform via `lstk terraform`; `tflocal` is deprecated | Confirmed (LocalStack Terraform page). The page prefers the virtual-hosted S3 endpoint and path-style only as a fallback. |
| LocalStack Lambda on Hobby with SQS/Kinesis/DynamoDB event source mappings; needs the Docker socket | Confirmed (docs.localstack.cloud/aws/services/lambda). Layers need a licence (plan not stated); container images unverified. Both avoided with a zip package. |
| LocalStack S3 notifications to SQS | Confirmed: the tutorial docs.localstack.cloud/aws/tutorials/iam-policy-stream creates `aws_s3_bucket_notification` to an SQS queue with Terraform and receives the message. The tutorial does not say which plan it needs, and the S3 service page (100 of 116 operations, available from Hobby) does not mention notifications: behavior on Hobby is unverified, and so is whether events carry `sequencer`; both are tested in the Terraform step. |
| S3 events: delivered at least once, not guaranteed in order; `sequencer` orders events for one key (left-pad, then compare) | Confirmed (AWS S3 user guide, "Event Notifications" and "Event message structure"). `sequencer` is sent for PUT and DELETE only. The guide warns that a function writing to the bucket that triggers it can loop and recommends a prefix for incoming objects. |
| `dbt build`: a failing test skips downstream resources; a model is created before its data tests run | Confirmed (docs.getdbt.com/reference/commands/build: "The model is materialized. Data tests are run on the model.") |
| DuckDB transactions roll back INSERT/DELETE | Confirmed (duckdb.org transactions page). Whether DDL rolls back is not stated -> promotion uses DELETE/INSERT only, and a unit test injects a failure mid-promotion. |
| OpenAQ API: key required, 60 requests/min and 2,000/hour, 429 and possible ban on repeated excess | Confirmed (docs.openaq.org/using-the-api/rate-limits and /api-key; registration at explore.openaq.org/register) |
| OpenAQ archive: `openaq-data-archive` bucket, csv.gz, one file per location-day with all sensors, written 72 h after day end, may be patched later | Confirmed (docs.openaq.org/aws/about). The page does not promise a file for every day. |
| OpenAQ archive header and unit spelling | The documented example header is `location_id,sensors_id,location,datetime,lat,lon,parameter,units,value` and its rows show `µg/m³`, which is why the unit rule normalizes spellings before comparing. (The page's column table writes `sensor_id` and `unit`; the example file writes `sensors_id` and `units`.) The example is location 2178, "Del Norte-2178", parameter pm10, from 2023. |
| What 2026 files actually contain (unit bytes, a PM2.5 sensor at location 2178, hourly spacing) | Confirmed 2026-10-05 in check 0.4 on the file of 21 September 2026: the header as documented, with every field name in double quotes; PM2.5 is sensor 3920 with the unit text `µg/m³`; rows are whole hours apart. |
| OpenAQ archive can be read anonymously | Confirmed: four unsigned list requests succeeded on 2026-10-03; the quick-start uses `--no-sign-request`. |
| Completeness of location 2178 in the archive | September 2026: 20 files, for 1-19 and 21 Sep; none for 20 Sep or 22-30 Sep; the newest was written on 25 Sep. Q2 2026: April 29 files (none for 26 Apr), May 31, June 28 (none for 21-22 Jun) = **88 of 91 days**. Files appear four days after the day at about 06:00 UTC. This is a dated observation of one location, not a property of the archive; completeness is measured per station in pre-flight and enforced by the gate's one-row-per-date test. |
| OpenAQ timestamps mark the end of the period | Confirmed (docs.openaq.org/using-the-api/dates-datetimes: "exclusive time-ending standard"; 03:00 means 02:00 until 02:59) |
| OpenAQ terms: attribute OpenAQ, comply with each provider's terms; one API key per person; no scraping | Confirmed (docs.openaq.org/about/terms) |
| OpenAQ locations expose `licenses` (id, name, attribution, dateFrom, dateTo), `provider`, `owner`, `timezone`, `sensors` | Confirmed (docs.openaq.org/resources/locations) |
| OpenAQ licences resource exposes `redistributionAllowed`, `attributionRequired`, `commercialUseAllowed`, `modificationAllowed`, `shareAlikeRequired`, `sourceUrl` | Confirmed (docs.openaq.org/resources/licenses) |
| Station, sensor and licence for P1 | Unverified (API key needed) -> checks above. Location 2178 is a candidate on archive coverage alone. |
| WHO 2021 24-hour PM2.5 guideline 15 µg/m³, defined on the 99th percentile (3-4 exceedance days a year) | **Corroborated; the WHO table itself was not read.** The guideline PDF on iris.who.int and two other IRIS URLs returned HTTP 403. Two WHO pages show the table as an image; their text does confirm "99th percentile (i.e. 3-4 exceedance days per year)". A WHO compendium PDF downloaded but could not be rendered here. A search restricted to who.int returned 15 µg/m³ for the 24-hour level. The value is not in real doubt; the 2-minute manual check stays in the checks above. |
| Ollama supports tool calling (docs examples use qwen3) and JSON-schema output through `format` | Confirmed (docs.ollama.com). The qwen3 library page shows a "tools" tag and sizes from 0.6b to 235b (4b is 2.5 GB, 8b 5.2 GB, 14b 9.3 GB). Its licence was not shown: unverified; check it before publishing agent results. |
| DuckDB and Iceberg: tables read directly from a path are read-only; writing needs an attached Iceberg REST catalog | Confirmed (duckdb.org Iceberg extension overview). Write support arrived in DuckDB 1.4.0 according to a search summary of DuckDB's release announcement; the announcement itself was not opened. Current versions on PyPI: DuckDB 1.5.6, dbt-duckdb 1.11.0. dbt-duckdb can target an attached Iceberg catalog only in part, checked 2026-10-06 in check 0.3 with dbt-core 1.12.5: seeds, incremental models and data tests work; a plain table, a view and `--full-refresh` are refused. |
| Sensor.Community archive: daily folders from 2015 to today plus monthly CSV files, openly downloadable | Confirmed (archive.sensor.community directory listing). Layout checked 2026-10-04: days from 2015 to 2025 sit under year folders, 2026 days at the top level; one file per sensor per day, named like `2026-09-01_bme280_sensor_141.csv`, so temperature and humidity come from a different sensor id than PM. **Dropped as a source on 2026-10-05** because of its licence, in the next row. |
| Sensor.Community data licence | **Unclear, so the source was dropped.** Read 2026-10-05 in task 0.5: the footer of sensor.community names the Database Contents License (DbCL) v1.0, and its clause 2.2 says "You must comply with the ODbL". Sensor.Community itself states neither a credit nor share-alike terms, and the archive and its files carry no licence text. The owner dropped the source and chose openSenseMap. |
| openSenseMap archive: a folder per day, a folder per box inside it, one CSV per sensor and one JSON metadata file; openly downloadable | Tried by hand 2026-10-05 (archive.opensensemap.org): the listing starts on 2014-06-03. It does not have a folder for every day: check 0.5b found 16 days without one from 2025-01-01 to 2026-10-03, 2025-01-23 and 2025-01-28 among them. One box was downloaded without credentials for 2026-10-04 and for 2025-01-01. On both days it had PM2.5, PM10, temperature and humidity files with the header `createdAt,value` and UTC timestamps, about 2.5 minutes apart, and a metadata file giving each sensor's name, unit and hardware. This was one box, not a scripted check: the lag, other boxes and how owners name sensors are unverified -> checks above. |
| openSenseMap data licence | Read 2026-10-05 in the site's own text (opensensemap.org/translations/en_US.json): "All data is licensed under Public Domain Dedication and License 1.0 and free to use", and a person registering a box agrees "that the sensor data you submit can be freely used by the public according to the" same licence. The licence summary (opendatacommons.org/licenses/pddl/summary) says "The PDDL imposes no restrictions on your use of the PDDL licensed database." The full licence text was not read -> checks above. |
| Open-Meteo air-quality API: hourly PM2.5 from CAMS (11 km Europe, 45 km global), no key for non-commercial use, attribution to CAMS and Open-Meteo required, reanalysis from 2013 | Confirmed (open-meteo.com air-quality API docs). Rate limits are not stated on that page. |
| Open-Meteo historical weather API: hourly `temperature_2m` and `relative_humidity_2m`; ERA5 at about 25 km from 1940, ERA5-Land at about 11 km from 1950, ECMWF IFS at 9 km from 2017; no key for non-commercial use | Confirmed 2026-10-04 (open-meteo.com/en/docs/historical-weather-api). Rate limits and the exact licence text are not on that page. |
| OGC SensorThings API Part 1: Sensing, version 1.1, has eight entities: Thing, Location, HistoricalLocation, Datastream, Sensor, ObservedProperty, Observation, FeatureOfInterest | Confirmed 2026-10-04 (docs.ogc.org/is/18-088/18-088.html). UCUM 1.9 is a normative reference; whether a unit must be a UCUM code was not read. The property lists of Datastream and Observation were not read. |
| CF standard names used in the vocabulary | Checked 2026-10-04 on standard-name table v95 (16 September 2026): `air_temperature` with unit K confirmed on the table. `mass_concentration_of_pm2p5_ambient_aerosol_particles_in_air` with unit kg m-3 and `relative_humidity` were seen only in search summaries; the table page was too long to read to those entries -> checks above. |
| UCUM spellings `ug/m3`, `Cel`, `%` | **Unverified**; from general knowledge, the UCUM specification was not opened -> checks above. |
| DCAT 3 is a W3C Recommendation with classes Catalog, Dataset, Distribution and DataService, and properties for licence (`dcterms:license`), time range (`dcterms:temporal`), area (`dcterms:spatial`) and update frequency (`dcterms:accrualPeriodicity`) | Confirmed 2026-10-04 (w3.org/TR/vocab-dcat-3, Recommendation of 22 August 2024). |
| OpenAQ parameters resource exposes `id`, `name`, `units`, `displayName`, `description`; `pm25` is the documented example | Confirmed 2026-10-04 (docs.openaq.org/resources/parameters). Whether the chosen stations report temperature or humidity: unverified -> checks above. |
| The MCP Python SDK and PyIceberg are published on PyPI | Confirmed that the packages exist (2.3.0 and 0.12.0). Their behavior is unverified. |
| DynamoDB Local (for the open decision in Part 1) | Checked 2026-10-04 on the AWS DynamoDB developer guide: it comes as a download (needs Java), a Maven dependency or a Docker image; the access key and region "don't have to be valid AWS values"; it writes a database file unless started with `-inMemory`; AWS states it is "intended for development and testing purposes only"; reads are eventually consistent; conditional writes are not among the listed differences from the web service. Not checked: its licence terms, and whether the conditional pointer update behaves the same as on LocalStack and real DynamoDB. |

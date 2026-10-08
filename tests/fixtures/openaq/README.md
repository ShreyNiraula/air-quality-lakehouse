# OpenAQ test data

Real day files of the OpenAQ archive, unchanged: January 2025 and January 2026 of the three Berlin monitors, so that a month can be compared with the same month a year earlier.

| | |
|---|---|
| Files | 186: 3 monitors, 2 months, 31 days each |
| Monitors | 3019 Berlin Mitte, 4762 Berlin Schildhornstraße, 4767 Berlin Frankfurter Allee |
| Source | `https://openaq-data-archive.s3.amazonaws.com`, each file at the path it has here below `tests/fixtures/openaq/` |
| Downloaded | 7 October 2026, by `uv run python -m airquality.openaq --fixtures` |
| Unchanged | `tests/test_openaq.py` compares the MD5 and the size of every file with the manifest, `manifests/generated/openaq-files.csv`, which has them from the archive's own listing |

## Licence

The files may be passed on, with a credit. The manifest records it (`manifests/README.md` has the detail):

| | |
|---|---|
| Licence | ODC-BY 1.0 in OpenAQ's record; CC-BY in the EEA's legal notice |
| Redistribution | allowed |
| Credit, which is required | European Environment Agency (EEA), via OpenAQ |

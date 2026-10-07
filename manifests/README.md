# Source manifests

A manifest says, for one source, which stations the project uses, what each sensor measures and in which unit text, under which licence, and which files exist. The files in `generated/` are written by a script and are not edited by hand:

```
uv run python -m airquality.manifests
```

It needs the OpenAQ key in `OPENAQ_API_KEY` and takes about a minute. `tests/test_manifests.py` validates what is committed.

- `generated/openaq.json`: the six reference monitors of Berlin and Wien, the owner's choice of 6 October 2026 (task 0.8a).
- `generated/openaq-files.csv`: one line per day file from 1 January 2025, with its MD5 and size.
- The openSenseMap manifest follows in task 0.8b.

## The licence of the OpenAQ monitors

Two sources state it, and the manifest quotes both with their addresses.

- **OpenAQ's own record** for each monitor names ODC-BY: attribution required; redistribution, modification and commercial use allowed; share-alike not required. The script reads this record for every monitor, and the test fails if one disagrees with the manifest.
- **The EEA**, which supplies these monitors' data to OpenAQ, names CC-BY in its legal notice, with the same permissions, and adds that the meaning of the content must not be distorted. The notice is general; the page of the air-quality dataset itself could not be read by a script.
- **The two names differ and the permissions agree.** OpenAQ gives the party to credit only as "Unknown Governmental Organization". The owner kept the monitors on 6 October 2026, with the credit line "European Environment Agency (EEA), via OpenAQ".

## What the OpenAQ manifest shows (written 7 October 2026)

- **3,706 day files and 122 dates with no file**, for six monitors from 1 January 2025 to 30 September 2026.
- **Every monitor has a PM2.5 sensor with the unit text `µg/m³` and a reading every 3600 seconds**, read from each monitor's first day file.
- **The gaps come in blocks shared by a city.** All three Berlin monitors have no file from 15 to 23 August 2026. All three Wien monitors have none from 18 to 21 April 2025 and from 7 to 18 October 2025. No monitor has a file for 3 May 2025.
- **The newest days of Wien have no file yet.** The Wien monitors have none from 21 or 22 September 2026 to the end. Check 0.4 measured the archive's delay on one station in the USA, as four days; these files may be late, not missing. A later run of the script will tell.
- **The hash is the MD5 that the archive's listing gives for each file** (its `ETag`), so no file had to be downloaded for it. Checked by hand on three files: the MD5 of the download equals the listed one.

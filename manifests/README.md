# Source manifests

A manifest says, for one source, which stations the project uses, what each sensor measures and in which unit text, under which licence, and which files exist. The files in `generated/` are written by a script and are not edited by hand:

```
uv run python -m airquality.manifests
```

It needs the OpenAQ key in `OPENAQ_API_KEY` and takes about twelve minutes, nearly all of it for the openSenseMap files, which are downloaded one by one. `tests/test_manifests.py` validates what is committed.

- `generated/openaq.json`: the six reference monitors of Berlin and Wien, the owner's choice of 6 October 2026 (task 0.8a).
- `generated/openaq-files.csv`: one line per day file from 1 January 2025, with its MD5 and size.
- `generated/opensensemap.json`: the seven openSenseMap boxes within 1 km of those monitors (task 0.8b).
- `generated/opensensemap-files.csv`: one line per file the project reads of January 2025, with its MD5 and size: each box's metadata file of the day, and the day files of its PM2.5, temperature and humidity sensors. The backfill of both sources (task 2.6) extends it to the whole period.

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

## What the openSenseMap manifest shows (written 7 October 2026)

The licence is PDDL 1.0, read in check 0.5b: everything is allowed and no credit is required.

- **752 files and 116 dates with no file**, for seven boxes in January 2025: 188 metadata files, and 188 files each of the PM2.5, temperature and humidity sensors. On every day a box has all four files or none.
- **Each box has its coordinates, and its first and last reading.** The coordinates are the ones its metadata file of 1 January 2025 gives. The first and last reading are those of its PM2.5 sensor within January 2025, not of the whole period.
- **Every box has exactly one sensor of each of the three kinds**, named `PM2.5`, `Temperatur` and `rel. Luftfeuchte`, with the unit texts `µg/m³`, `°C` and `%`. Each box also has a PM10 sensor, and four have a pressure sensor; the manifest lists them with no parameter, and their files are not listed, because the project does not read them. The sensors were placed by the rule of check 0.5b, and the names were read by eye.
- **Every PM2.5 sensor is an SDS011.** A reading comes about every 125 to 187 seconds, and every 309 seconds from one box.
- **No box has a file for 23 or 28 January 2025.** The archive has no folder for those two days at all, as check 0.5b found.
- **One Wien box has a long gap.** `WA_Luftsensor`, the box near monitor 4563, has no file from 12 to 24 January 2025: 17 files in 31 days. Wien has exactly three pairs, and a pair is compared only if it shares 70% of hours.
- **One Berlin box ends early.** `Feinstaub Scharnweber`, near monitor 4767, has no file from 29 to 31 January 2025.
- **The times in the files are UTC.** The manifest gives each box the timezone of its city, which the daily tables need.

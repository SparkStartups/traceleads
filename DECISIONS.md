# Decisions

One rule is behind all of these: **precision over recall**. Flagging an honest business costs it
an inspection and its good name. Missing a lead only costs coverage.

## 1. Google through Oxylabs, not the Places API

The Places API's terms limit storing results, and this whole thing is built on monthly snapshots
we keep. So Oxylabs renders the normal Google Maps search page and we parse it. Staff and tax come
from open registers (JAR, Sodra, VMI), all downloaded by code.

## 2. Three kinds of business

We picked cafés and bakeries, car repair, and dental clinics. Each has enough Vilnius companies to
compare, a clear activity class and Google category, and customers who pay on the spot. Hair and
beauty was left out because it's mostly self-employed people renting chairs, who aren't companies.
Bars and vets were left out because there are too few to compare.

## 3. Collect once a month, keep everything

The sources mostly show only today. The register and VMI publish their current state, and
Google's results change every day. If October isn't saved in October, it's gone.

So `collect` does all the downloading in one go and saves two things: the raw files exactly as
downloaded, and a small snapshot with only the columns we use (about 1.5 million rows, 12 MB of
Parquet, small enough for git). Everything after that works from the snapshot, offline. This
pays off in a few ways:

- Anyone can rebuild October with `docker compose up`: no API key, no network, no cost.
- Google pages cost money, so each one is rendered once, not on every build.
- Every raw file's SHA-256 is recorded, so any lead can be traced back to the exact file.
- An individual enterprise (IĮ) is often named after its owner. Those names are dropped when
  the snapshot is written, so they never reach git (raw files stay on the local disk only).

## 4. Transform in DuckDB, with plain SQL

A month is small: 840,000 Sodra rows, 390,000 VMI rows, 235,000 companies and about 1,000 Google
listings. The work is joins, text matching and comparing medians, which is what SQL is good at.

- **DuckDB** is a database in one file, with no server. It reads the Parquet snapshots directly
  and rebuilds October in about 5 seconds. The result is one file the app can open.
- **PostgreSQL** would need a server running next to the app, a schema to migrate and a step to
  load the files. That's a lot of setup for one analyst.
- **Polars** is just as fast, but it's a Python dataframe library. The logic would be Python
  code, and there'd be no database file for the app and its SQL console to share. In SQL, the
  analyst can read the models and ask their own questions in the same language.

Every build starts from zero and writes a new file, so there are no migrations and the same
snapshot always gives the same list.

**Matching.** Google doesn't say which company runs a place, so we compare names and addresses.
A café called "Kavos namai" on Gedimino pr. 1 and UAB "Kavos namai" registered at Gedimino pr. 1
is a safe match. Five rules go from safest to weakest, and the first one that fits wins. Only the
three safest link on their own; the other two put the place in a queue for a person to decide.

**Scoring.** A company is compared with similar ones: the same kind of business, one place each.
A lead is busy on Google, yet has both far fewer staff and far less tax than its peers (a third
of their median or less). One gap only puts it on watch. When data is missing, such as no tax
record or too few peers, the company is held with the reason shown instead of guessed. There's
no machine learning model: there are no confirmed cases to learn from yet, and an analyst needs a
reason they can read out loud.

## 5. Show it in Streamlit

The analyst needs to see the list, check the evidence behind each lead, and ask their own
questions. Streamlit is a Python library, so the app lives in the same repo, starts with the
same `docker compose up`, and reads the DuckDB file directly, read-only. When a new build
finishes, the app shows the new data without a restart.
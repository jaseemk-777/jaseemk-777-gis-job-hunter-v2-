# QUICK SETUP — GIS Job Hunter V2

1. **Create PRIVATE repository**: https://github.com/new → `gis-job-hunter-v2` → Private.
2. **Unzip** `GIS_Job_Hunter_V2.zip`. Upload its contents to the repo **including hidden `.github/` folder**. GitHub Desktop is easiest.
3. **Test**: Actions → GIS Job Hunter V2 → Run workflow. No Gmail connection is required for this test.
4. **Read results**: Actions → completed run → `gis-hunter-report-...` artifact, or `reports/latest.md` in your private repo.
5. **Turn on Gmail summaries (optional)**: GitHub repo → Settings → Secrets and variables → Actions → Secrets → add `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (a Google App Password, NOT your normal Gmail password; requires Google two-step verification where supported).
6. **More Indian jobs (recommended)**: Set personal LinkedIn/Naukri/Indeed/NaukriGulf alerts for GIS/Remote Sensing/Geospatial/Climate; use Gmail label `GIS-JOB-ALERTS`, expose in IMAP, set `settings.json` → `sources.gmail_alerts=true`, and repo variable `GMAIL_ALERTS_ENABLED=true`.
7. **More country searches (optional)**: Register for an Adzuna API key, add `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` secrets, and set `sources.adzuna=true` in `settings.json` (country coverage varies).
8. **Verify GitHub write access** if seen jobs don't persist: Settings → Actions → General → Workflow permissions → Read and write, if available.

**Schedule:** Every day at approximately **2:07 p.m. IST** and **11:07 p.m. IST**. GitHub runs it even when your computer is off.

**Default sources:** AiDASH, Planet, Tomorrow.io official boards; Remotive; Himalayas (including India-specific queries); Arbeitnow European jobs.

**Important:** Finds and scores leads; generates review-only application messages; deduplicates; emails a digest **to you only**. **No applications or recruiter emails are sent**. Original 95 leads are audited, but many are search links and cannot be confirmed as active.

Full guide: `README_START_HERE.md`.

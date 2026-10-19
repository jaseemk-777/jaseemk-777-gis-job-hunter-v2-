# GIS Job Hunter V2 — GitHub Actions + Gmail

**A working, testable repository starter** for twice-daily GIS job discovery. It builds on your original 95 leads and is designed for your background (GIS, QGIS, ArcGIS, remote sensing, Google Earth Engine, Python, climate risk). **This ZIP has not been deployed or connected to your account.** It does **not** mass-apply or email employers.

## What it searches

| Source | Enabled by default? | Coverage | Needs credentials? |
|---|---|---|---|
| **Official Greenhouse ATS** (AiDASH, Planet, Tomorrow.io) | Yes | Company offices worldwide, India included if positions available | No |
| **Remotive** | Yes | Worldwide remote, with location restrictions that must be checked | No |
| **Himalayas Remote Jobs API** | Yes | Remote roles, location restrictions and dates when available | No; optional free API key |
| **Arbeitnow Europe jobs** | Yes | European on-site/remote listings | No |
| **Adzuna job search API** | No | Country searches, including India if supported by your API account; the API may reject specific markets | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` |
| **LinkedIn, Naukri, Indeed alerts from Gmail** | No | India/Middle East/worldwide depending on alerts you create | Gmail app password, Gmail alert label and enabled settings |
| **Original 95 leads** | Preserved | Old research baseline; company-and-role cross-check against live official ATS sources | No |

**Coverage limits:** Only three *official employer feeds* are connected by default, not 89 company feeds. The three global feeds expand coverage but can miss Indian, NGO and Gulf opportunities. To make India discovery comprehensive, configure your personal LinkedIn/Indeed/Naukri/NaukriGulf **job alerts**, add real employer board slugs and optionally subscribe to a permitted country-search API. It does not scrape portals or pretend to find every job on the internet.

## Schedule

The `.github/workflows/gis-job-hunter-v2.yml` schedule uses `timezone: Asia/Kolkata`:

- **Every day around 2:07 PM IST**
- **Every day around 11:07 PM IST**

The minute 07 avoids top-of-hour congestion. GitHub schedules can be delayed and are not exact-time guarantees. You can also run it any time by clicking **Actions → GIS Job Hunter V2 → Run workflow**.

**Your laptop may be OFF.** GitHub supplies the runner. You only need a device for initial setup and to review results.

## Deployment (one-time, about 15–30 minutes)

1. Create a **private** GitHub repository: https://github.com/new, e.g. `gis-job-hunter-v2`. **Keep it private**: reports can include email alert subjects and job links.
2. Unzip this package. Upload **everything**, preserving `.github/workflows/gis-job-hunter-v2.yml`. GitHub Desktop is easiest because this `.github` folder is hidden on some systems. Keep the original folder structure.
3. Open the repository **Actions** tab. Click **GIS Job Hunter V2 → Run workflow**. The program scans public APIs without any email configuration.
4. The workflow writes `reports/latest.md`, `reports/new_jobs.csv`, `reports/posted_last_7_days.csv`, `reports/all_matching.csv`, `reports/Original_95_Audit.csv`, `reports/drafts_to_review.md` and `reports/run_stats.json`. Download the `gis-hunter-report-...` artifact from the run or view the files in your private repo.
5. To receive reports by Gmail: enable Google 2-Step Verification and, if available for your account, create a Google **App Password** at https://myaccount.google.com/apppasswords. Your normal Gmail password is **not** used. Open GitHub **Settings → Secrets and variables → Actions → New repository secret**, and add:
   - `GMAIL_ADDRESS` = your Gmail address
   - `GMAIL_APP_PASSWORD` = your app password (16 characters)
   Don't post those secrets in chats or save them in any repository file. The sender emails **only this account**, not recruiters. If App Passwords are unavailable for your account, skip this feature and use GitHub's reports or connect an alternative mail provider separately.
6. To connect **LinkedIn, Naukri, Indeed and NaukriGulf job alerts**, sign up for job email alerts on the job platforms, selecting keywords GIS Analyst, GIS Specialist, Remote Sensing, Geospatial Analyst, Climate Risk, Google Earth Engine, Spatial Data Analyst, Junior GIS and similar. Make a Gmail label `GIS-JOB-ALERTS` and add Gmail filters that label these messages; in Gmail settings ensure the label is visible in IMAP. In `settings.json`, change `"gmail_alerts": false` to `true`, and add a GitHub repository **variable** `GMAIL_ALERTS_ENABLED=true`. The script reads links from labelled messages; email **subjects and links are unverified leads** until you check the vacancy. It does **not** sign into or scrape LinkedIn, Indeed or Naukri.
7. To add more **official employer feeds**, inspect the company's actual careers link. If it uses `job-boards.greenhouse.io/COMPANY`, `jobs.lever.co/COMPANY`, or `jobs.ashbyhq.com/COMPANY`, add an entry to `boards.json` with `provider` = `greenhouse`, `lever`, or `ashby`, `slug`=the actual slug, `enabled`=true. **Never guess slugs**; they may refer to another employer.
8. **Optional larger country search**: register an Adzuna developer account at https://developer.adzuna.com/ and create GitHub Secrets `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`. In `settings.json`, set `"adzuna": true`. Some requested countries might not be supported; this is reported as a source warning, not silently ignored. Customize `adzuna_country_codes` and `adzuna_searches` to control quota/use. **India coverage cannot be guaranteed by Adzuna**.
9. If the GitHub workflow cannot commit reports/seen state, go to repository **Settings → Actions → General → Workflow permissions** and enable the workflow to create commits (Read and write permissions), where permitted by your organization's rules. Otherwise you'll receive repeats because GitHub runners are temporary.

## What reports mean

- `reports/new_jobs.csv`: newly **discovered by this tracker**, not necessarily posted this week.
- `reports/posted_last_7_days.csv`: matching jobs **whose source exposes a publication date within seven days**. Date is provider-reported, not independently verified.
- `reports/all_matching.csv`: all currently reported matches; jobs can close between scans.
- `reports/Original_95_Audit.csv`: tracks each old entry separately. An exact title+employer match on the *three connected official ATS feeds* is flagged. Search-results links are **not verified jobs**.
- `reports/drafts_to_review.md`: customized opening message templates for review. **Not sent.**
- `reports/latest.md`: a geographic breakdown and source-health warnings.
- `data/seen.json`: persistent de-duplication. The workflow commits it back to the private repository after a successful scan.

Fit scoring favours GIS/geospatial titles and your QGIS, ArcGIS, remote sensing, Python, SQL and disaster/climate experience, prioritizes junior/analyst/associate jobs and marks 4+ years as stretch. It filters out electrical **gas-insulated switchgear** jobs. Unknown salaries are not filtered out; your negotiation target is roughly ₹45,000–₹60,000/month (₹5.4–7.2 LPA). Salary and actual eligibility always require human verification.

### International warnings

Himalayas country-restrictions are used when present: a remote job restricted to US/EU without India is **not recommended** as an India work-from-home option. Middle East restricted remote roles may remain as **relocation-only** candidates. Remotive and other listings without authoritative geographic eligibility are explicitly marked **unknown / check**. 'Worldwide remote' does not guarantee your country or timezone qualifies.

## Control and safety

- **This pipeline does not apply for jobs, upload your résumé to sites, send cold emails or auto-contact recruiters.** It creates potential application messages in a Markdown file for your review. Automating applications on employer systems requires separate permitted integrations and approval checks.
- Gmail credentials are secrets stored in GitHub, never placed in Python source or logs. Use a private repository.
- Because it processes external data and Gmail notifications, avoid putting personally sensitive data in job alerts or source fields. Store your résumé privately and submit to official applications yourself.
- These APIs are external and can change or rate-limit. The report records source failures rather than interpreting a failed source as zero openings.
- The same provider may show a post through multiple URLs; the deduplication uses URL/job IDs but isn't perfect across sites.
- Jobs may be too senior or require a different degree: a high score is an initial filter, not a guarantee of qualification.

## Run/test locally (optional)

You don't need to leave your laptop on; local run is for testing only. Requires Python 3.12 or later, no third-party packages:

```bash
python -m unittest discover -s tests -v
python job_hunter.py
```

If you have **no Gmail app password** set, emails won't be sent. Reports are still produced.

## References for the APIs/scheduling

- GitHub Actions schedule: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Greenhouse public job board: https://docs.greenhouse.io/job-board.html
- Remotive public remote jobs API and attribution: https://github.com/remotive-io/remote-jobs-api
- Himalayas remote jobs API and attribution: https://himalayas.app/docs/remote-jobs-api
- Arbeitnow public job API: https://blog.arbeitnow.com/blog/job-board-api
- Adzuna API: https://developer.adzuna.com/overview
- Google App Passwords: https://support.google.com/accounts/answer/185833

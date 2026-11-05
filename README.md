### Offsite Backup

Nightly database backup of a Frappe site to a private Microsoft 365 SharePoint library.

- One job at 02:30 site time: Frappe's own database dump (no attachments, no site config), uploaded in 10 MB pieces into one folder of one library, then the folder is pruned to the newest 30 files plus the first file of each of the last 12 months.
- One Single doctype, **Offsite Backup Settings**, holds the connection and the rules. A **Back up now** button runs the same job on demand.
- Every attempt is logged as an **Offsite Backup Run**; failures always send an email to the addresses in the settings.
- The app talks to Microsoft with an app registration limited to that one library (`Sites.Selected`). No user signs in, no refresh tokens, no other data is reachable.

See [docs/OPERATIONS.md](docs/OPERATIONS.md) for installation on a site, the Microsoft 365 setup, what runs when, and how to rehearse without a tenant.

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/sfgroupofcompanies/offsitebackup --branch develop
bench --site <site> install-app offsitebackup
```

Requires Frappe 15. No other app is needed.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/offsitebackup
bash scripts/setup-git-hooks.sh
```

Commit subjects follow Conventional Commits in lower case (`feat: …`, `fix: …`, `ci: …`, `docs: …`). Every change is one small pull request into `develop`; the test workflow installs the app on a fresh Frappe 15 site and runs the suite.

### Tests

```bash
bench --site <site> run-tests --app offsitebackup
```

The suite needs no Microsoft account: Microsoft is faked in the unit tests, and four end-to-end tests run the real HTTP client against `offsitebackup/integrations/microsoft/fake.py`.

### License

mit

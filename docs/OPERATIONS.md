# Offsite Backup — operations

Written for whoever installs, switches on and watches this app on a site.

## 1. What it does, in one picture

```
02:30 site time (or the "Back up now" button)
  └─ scheduled_backup → run_backup
       1. make_backup      Frappe's own `new_backup`, database only, fresh every time
       2. get_token        one POST to login.microsoftonline.com with the app registration
       3. upload_file      createUploadSession on <library>/<folder>/<file>, 10 MiB PUTs, 3 tries per piece
       4. prune_folder     keep newest N files + first file of each of the last M months, delete the rest
       5. run log          one "Offsite Backup Run" row: Success / Failed, file, size, seconds, message
          settings         Last Run On / Last File / Last Size / Last Result
          email            failure → always, to "Send Notifications To"; success → only if ticked
```

Nothing in a failed step raises to the scheduler: the run is marked Failed with a plain reason, the traceback goes to the Error Log, the failure email goes out.

What leaves the server: the database dump only. Frappe writes its usual `site_config_backup.json` next to the dump on the server's own disk; it is never uploaded, so the encryption key stays with the operator.

## 2. Microsoft 365 side (once per company)

Done by the tenant's **Global Administrator**; about 15 minutes. The three values at the end are typed straight into the settings form, never sent by chat or email.

1. **Library.** SharePoint → Create site → Team site, name `ERP Backups`, private. In its Documents library create one folder per site (for example `gva-sf`) and one `test` folder for rehearsals.
2. **App registration.** Entra admin centre → App registrations → New: name `ERP Backup`, single tenant, no redirect URI. Note the **Application (client) ID** and **Directory (tenant) ID**.
3. **Secret.** Certificates & secrets → New client secret, 24 months. Copy the value at once; put the expiry date in the calendar.
4. **Permission.** API permissions → Add → Microsoft Graph → Application permissions → `Sites.Selected` → Add, then **Grant admin consent**.
5. **Point the app at the one library** (SharePoint Administrator or Global Administrator):
   ```
   Install-Module PnP.PowerShell -Scope CurrentUser
   Connect-PnPOnline -Url https://<company>-admin.sharepoint.com -Interactive
   Grant-PnPAzureADAppSitePermission -AppId <client id> -DisplayName "ERP Backup" -Site https://<company>.sharepoint.com/sites/ERPBackups -Permissions Write
   ```
   Or in Graph Explorer as the admin: `POST https://graph.microsoft.com/v1.0/sites/<site-id>/permissions` with `{"roles":["write"],"grantedToIdentities":[{"application":{"id":"<client id>","displayName":"ERP Backup"}}]}`.

The app can then read and write that library and nothing else in the company.

## 3. Site side (once per site)

1. `bench get-app https://github.com/sfgroupofcompanies/offsitebackup --branch develop`, then `bench --site <site> install-app offsitebackup`. One app, one scheduled job, no new ports, no new Python dependencies beyond Frappe's.
2. Open **Offsite Backup Settings** (System Manager only):
   - SharePoint Site URL: `https://<company>.sharepoint.com/sites/ERPBackups`
   - Folder: this site's folder, e.g. `gva-sf`
   - Tenant ID, Client ID, Client Secret: from step 2
   - Keep Daily Backups 30, Keep Monthly Backups 12
   - Send Notifications To: the people who own backups, comma-separated
   - Send Email for Successful Backup: off (failures are always sent)
   - Backup Frequency: Daily (Weekly = Sundays only)
3. Tick **Enabled**, Save. The form refuses to save while enabled if any connection value is missing or the site URL is not https.
4. Press **Back up now**. Within a few minutes the **Offsite Backup Run** list shows a Success row and the file is in the library folder. If it shows Failed, the message says which step and why.
5. Leave it. The next run is at 02:30.

## 4. Watching it

- **Workspace "Offsite Backup"**: days since the last good backup, failed runs in the last 30 days, backup size per day.
- **Report "Offsite Backup Runs"**: every attempt in a date window.
- **Failure emails** are the alarm. A run that never starts (scheduler down) sends nothing, which is what the "days since last good backup" card is for.
- **Monthly**: download the newest file from the library and restore it on a scratch site (`bench --site scratch restore <file>`); open the site; compare a few counts. A backup that has not been restored is a hope, not a backup.
- **Every 24 months**: the client secret expires. Renew it in Entra, paste the new value into the settings.

Disk on the server: Frappe keeps its last few dumps under `sites/<site>/private/backups` and cleans them with its own job; this app does not add to that beyond one fresh dump per run.

## 5. Rehearsing without a tenant

For development and for proving a change before it goes anywhere near a real site, the app can be pointed at a local stand-in for Microsoft:

```bash
# in the bench
./env/bin/python -m offsitebackup.integrations.microsoft.fake /tmp/fake-library --port 8765
bench --site <test site> set-config offsitebackup_login_url http://127.0.0.1:8765
bench --site <test site> set-config offsitebackup_graph_url http://127.0.0.1:8765/v1.0
```

Fill the settings with any values (the site URL must still start with https) and press **Back up now**. The dump lands in `/tmp/fake-library/<folder>/`, byte for byte, and prune works on that folder. Remove the two config keys to talk to Microsoft again. Never set them on a real site: the fake accepts any credentials.

## 6. Where things are in the code

Folders by purpose; nothing at the package root except `hooks.py` and `__init__.py`.

| piece | file |
|---|---|
| settings doctype + validation | `offsitebackup/offsite_backup/doctype/offsite_backup_settings/` |
| run log doctype, `start_run` / `finish_run`, number-card method | `offsitebackup/offsite_backup/doctype/offsite_backup_run/` |
| access token from Microsoft | `offsitebackup/integrations/microsoft/token.py` |
| Graph client: site, folder, upload, list, delete | `offsitebackup/integrations/microsoft/graph.py` |
| fake Microsoft for rehearsals | `offsitebackup/integrations/microsoft/fake.py` |
| the dump (Frappe's `new_backup`, database only) | `offsitebackup/backup/dump.py` |
| prune rules | `offsitebackup/backup/prune.py` |
| `run_backup`: the chain, run log, Last Run fields, emails | `offsitebackup/backup/run.py` |
| scheduled entry (`scheduled_backup`, cron 30 2 * * * in `hooks.py`) | `offsitebackup/tasks/nightly.py` |
| "Back up now" (`backup_now`, whitelisted) | `offsitebackup/api/backup.py` |
| report, chart, number cards, dashboard, workspace | `offsitebackup/offsite_backup/{report,dashboard_chart,number_card,offsite_backup_dashboard,workspace}/` |
| tests | `offsitebackup/tests/` |

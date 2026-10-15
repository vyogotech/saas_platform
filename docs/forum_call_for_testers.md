# Call for testers: single-site multi-tenancy for Frappe/ERPNext v16

Hi everyone,

We are building [saas_platform](https://github.com/vyogotech/saas_platform), an open-source Frappe app that lets multiple tenants share one Frappe/ERPNext v16 site and database. Each tenant's data is kept separate at the row level. Before we go further, we would like developers to test it, especially by trying to read another tenant's data.

## How it works

- **Tenant column:** every table has a `tenant_id` column. A user's tenant is set when they log in.
- **Reports and raw SQL:** every `frappe.db.sql` SELECT is parsed with `sqlglot`, and a tenant filter is added for each table it reads. If a query cannot be filtered safely, it is rejected rather than run unfiltered.
- **List views and forms:** filtered through the standard permission hooks, plus a User Permission on the tenant's Company.
- **Tenant Admin:** a role profile that works like System Manager but cannot change site-wide settings such as DocTypes, Server Scripts or Roles. Tenant admins can manage their own tenant's users.
- **Subscriptions:** there are two levels. The platform bills its tenants, and tenants bill their own customers. Tenants never see the platform's billing records.
- **Naming series:** each tenant has its own.

Design notes: [docs/report_tenant_isolation.md](https://github.com/vyogotech/saas_platform/blob/main/docs/report_tenant_isolation.md)

## Installation notes

- **Use a fresh test site.** Records that already exist when the app is installed are marked as shared (`SYSTEM`), so every tenant can see them.
- **Install saas_platform last.** Install ERPNext and your other apps first. The `tenant_id` column is added to the tables that exist when saas_platform is installed, and saas_platform's hooks should run after the other apps' hooks.
- **Add the column again after new DocTypes.** If you install an app, update one, or create a custom DocType later, run:
  ```bash
  bench --site <site> execute saas_platform.patches.add_tenant_id_to_all_tables.execute
  ```
  Tables without the column are not filtered.
- **Restart afterwards.** Restart the web and worker processes after every install or update.
- **Optional platform company:** set `saas_platform_company` in `site_config.json` to choose which Company the platform bills tenants from. If it is not set, the default company is used.

### Docker (quickest)

```bash
git clone https://github.com/vyogotech/saas_platform && cd saas_platform

docker run -d --name saas-test -p 8000:8000 \
  -v "$(pwd)":/home/frappe/frappe-bench/apps/saas_platform \
  docker.io/vyogo/erpnext:sne-version-16

docker exec -it saas-test bash -lc "cd ~/frappe-bench && \
  bench --site dev.localhost install-app saas_platform && \
  bench --site dev.localhost migrate"
```

### Existing v16 bench

```bash
bench new-site tenants.test
bench --site tenants.test install-app erpnext        # and any other apps
bench get-app https://github.com/vyogotech/saas_platform
bench --site tenants.test install-app saas_platform  # last
bench --site tenants.test migrate
bench restart
```

### Testing

1. As Administrator, create two **Tenant** records.
2. Log in as each tenant's admin user.
3. Try to read the other tenant's data through reports, list views, link fields, dashboards and the REST API.

## What we would like tested

- **Reports:** both standard ERPNext reports and custom ones, especially those with complex SQL such as CTEs, subqueries, UNIONs or unusual joins. Tell us about any data leak, or any report that fails when it should work.
- **Custom apps:** whether your raw `frappe.db.sql` queries still behave correctly when logged in as a tenant user.
- **Roles:** anything the Tenant Admin profile is missing, or allows that it should not.
- **Background jobs:** whether documents created by the scheduler or other jobs are tagged with the correct tenant.
- **Performance:** we measured about 0.7 ms per query (p95) on our test data. Results from larger datasets would help.
- **PostgreSQL:** it is supported, but most of our testing has been on MariaDB.

## Known limitations

- Only SELECT queries are rewritten. Raw `UPDATE`, `DELETE` and `INSERT … SELECT` statements are not filtered yet.
- A Subscription created by a tenant can fail with `DuplicateEntryError` ([#2](https://github.com/vyogotech/saas_platform/issues/2)).

## Reporting issues

Please open a [GitHub issue](https://github.com/vyogotech/saas_platform/issues) with:
- the report or query,
- the user's role,
- what you expected and what actually happened.

Replies on this thread are welcome too.

Thank you for helping.

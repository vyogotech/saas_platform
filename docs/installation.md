# Installation Guide

## Getting Started

The `saas_platform` app is designed to be installed on a Frappe Bench that acts as the **Central Site** for your SaaS ecosystem.

### Prerequisites

- A working [Frappe Bench](https://github.com/frappe/bench) environment.
- ERPNext (v15 recommended).

### 1. Install the App

```bash
# From your frappe-bench directory
bench get-app https://github.com/varun-krishnamurthy/saas_platform.git
bench --site your-site-name.localhost install-app saas_platform
```

### 2. Configure Database Columns

The app includes a utility to add the `tenant_id` column to all tables in your database. This is a one-time setup step.

```bash
# Run the migration utility
bench --site your-site-name.localhost execute saas_platform.patches.add_tenant_id_to_all_tables.execute
```

### 3. Add Custom Fields

Ensure all core DocTypes have the `tenant_id` field added:

```bash
bench --site your-site-name.localhost execute saas_platform.utils.add_custom_fields.execute
```

### 4. Restart Bench

```bash
bench restart
```

## Verification

1. Log in to your site.
2. Check the **User** DocType; a read-only `tenant_id` field should now be present.
3. Every new record created will now automatically inherit the user's `tenant_id`.

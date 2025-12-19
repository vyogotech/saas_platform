# SaaS Platform

A multi-tenant SaaS foundation for Frappe/ERPNext, designed to manage tenant lifecycle, data isolation, and central authentication.

## Key Responsibilities

- **Multi-Tenant Foundation**: Adds `tenant_id` to all relevant DocTypes (including `User`) to ensure strict row-level data isolation.
- **Central Authentication**: Acts as the Identity Provider (IdP) for the entire ecosystem.
- **Tenant Lifecycle**: Manages the creation of tenants, customer billing accounts, and subscriptions.
- **Core of the Microservice Ecosystem**: Provides the critical `tenant_id` metadata required by the **Frappe Microservice Framework** to perform cross-service authentication and data segregation.

## Documentation

- [Multi-Tenant Architecture](docs/architecture.md)
- [Implementation Guide](docs/implementation.md)
- [Microservice Integration Guide](docs/integration.md)
- [Full Installation Guide](docs/installation.md)

## Installation Quick Start

```bash
# 1. Install app
bench get-app https://github.com/varun-krishnamurthy/saas_platform.git
bench --site [your-site] install-app saas_platform

# 2. Migration
bench --site [your-site] execute saas_platform.patches.add_tenant_id_to_all_tables.execute
bench --site [your-site] execute saas_platform.utils.add_custom_fields.execute

# 3. Restart
bench restart
```

## License

MIT
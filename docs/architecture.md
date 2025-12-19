# Multi-Tenant SaaS Architecture

## Overview

This document describes the multi-tenant architecture implemented on top of ERPNext/Frappe for delivering ERPNext as a SaaS platform.

## Core Concepts

### Tenant

A **Tenant** represents a customer organization subscribing to your SaaS platform. Each tenant:

- Has a unique `tenant_id` (e.g., `acme-corp-a1b2c3d4`)
- Can have multiple Companies (for their own accounting)
- Has one Subscription linking them to a Subscription Plan
- Has isolated data - they only see their own records

### Data Isolation

All business data is isolated by `tenant_id`:

```
┌─────────────────────────────────────────────────────────────────┐
│                        ERPNext Database                          │
├─────────────────────────────────────────────────────────────────┤
│  tenant_id = "SYSTEM"     │  Shared/Platform data               │
│  (Customers, Subscriptions for billing)                         │
├─────────────────────────────────────────────────────────────────┤
│  tenant_id = "acme-abc123" │  Tenant A's data                   │
│  (Companies, Items, Orders, Invoices, etc.)                     │
├─────────────────────────────────────────────────────────────────┤
│  tenant_id = "globex-def456" │  Tenant B's data                 │
│  (Companies, Items, Orders, Invoices, etc.)                     │
└─────────────────────────────────────────────────────────────────┘
```

## Entity Relationships

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           PLATFORM LAYER (tenant_id = SYSTEM)            │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────┐         ┌──────────────────┐      ┌──────────────────┐ │
│  │   Tenant    │────────▶│    Customer      │◀─────│   Subscription   │ │
│  │             │         │ (YOUR customer   │      │                  │ │
│  │ tenant_id   │         │  for billing)    │      │ party_type:      │ │
│  │ tenant_name │         │                  │      │   Customer       │ │
│  │ subdomain   │         │ tenant_id=SYSTEM │      │ party: Customer  │ │
│  │ admin_email │         └──────────────────┘      │                  │ │
│  │ subscription│─────────────────────────────────▶│ plans: [         │ │
│  │ status      │                                   │   Free Plan      │ │
│  │ trial_expiry│                                   │ ]                │ │
│  └─────────────┘                                   │ tenant_id=SYSTEM │ │
│                                                    └────────┬─────────┘ │
│                                                             │           │
│                                                             ▼           │
│                                                 ┌──────────────────────┐│
│                                                 │  Subscription Plan   ││
│                                                 │  (Free Plan, Pro,    ││
│                                                 │   Enterprise, etc.)  ││
│                                                 │  tenant_id=SYSTEM    ││
│                                                 └──────────────────────┘│
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                      TENANT DATA LAYER (tenant_id = tenant's ID)         │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│  │  Company 1  │    │  Company 2  │    │  Company N  │                  │
│  │  (tenant's  │    │  (tenant's  │    │  (tenant's  │                  │
│  │   own co.)  │    │   own co.)  │    │   own co.)  │                  │
│  │             │    │             │    │             │                  │
│  │ tenant_id=  │    │ tenant_id=  │    │ tenant_id=  │                  │
│  │ acme-abc123 │    │ acme-abc123 │    │ acme-abc123 │                  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                  │
│         │                  │                  │                          │
│         ▼                  ▼                  ▼                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                     All Business Documents                          │ │
│  │  Sales Orders, Purchase Orders, Invoices, Items, Stock Entries,   │ │
│  │  Journal Entries, Customers (tenant's customers), Suppliers, etc.  │ │
│  │                                                                     │ │
│  │  All have: tenant_id = "acme-abc123"                               │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## Tenant Onboarding Flow

When a new tenant signs up:

```
1. Create Tenant
   ├── Generate unique tenant_id (e.g., "acme-corp-a1b2c3d4")
   │
2. Create Customer (tenant_id = SYSTEM)
   ├── This is YOUR customer for billing purposes
   ├── Visible to platform administrators
   │
3. Create Company (tenant_id = tenant's ID)
   ├── This is the tenant's default company
   ├── Only visible to the tenant
   │
4. Create/Update Admin User (tenant_id = tenant's ID)
   ├── User is linked to tenant via tenant_id
   ├── Roles: System Manager, Accounts Manager, etc.
   ├── On login, tenant_id is set in session
   │
5. Create Subscription (tenant_id = SYSTEM)
   ├── Links Customer to Subscription Plan
   ├── Sets trial period (14 days)
   └── Status: Trialling
```

## User-Tenant Linking

### Session Management

When a user logs in, the `on_session_creation` hook sets `tenant_id` in the session:

```python
# hooks.py
on_session_creation = "saas_platform.utils.tenant.on_session_creation"
```

```python
# utils/tenant.py
def on_session_creation(login_manager):
    user = login_manager.user

    # Administrator always gets SYSTEM
    if user == "Administrator":
        frappe.session['tenant_id'] = "SYSTEM"
        return

    # Get tenant_id from User document
    user_doc = frappe.get_doc("User", user)
    if user_doc.tenant_id:
        frappe.session['tenant_id'] = user_doc.tenant_id
```

### User Custom Field

User DocType has a `tenant_id` Custom Field:

- Read-only (set automatically)
- Visible in list view for administrators
- Used for session tenant_id lookup

## Database Schema

### tenant_id Column

Added to 689+ tables via ALTER TABLE:

```sql
ALTER TABLE `tabCompany` ADD COLUMN `tenant_id` VARCHAR(255);
CREATE INDEX `idx_tenant_id` ON `tabCompany` (`tenant_id`);
```

### Custom Fields

Added `tenant_id` Custom Field to 21 core DocTypes:

- Company, Customer, Supplier, Item
- Sales Order, Purchase Order, Sales Invoice, Purchase Invoice
- Quotation, Payment Entry, Journal Entry
- Delivery Note, Purchase Receipt, Stock Entry
- Lead, Opportunity, Project, Task, Issue
- Contact, Address

## Permission System

### Hooks Configuration (hooks.py)

```python
doc_events = {
    "*": {
        "before_insert": "saas_platform.utils.set_tenant_id"
    }
}

permission_query_conditions = {
    "*": "saas_platform.utils.tenant.get_permission_query_conditions"
}
```

### Automatic tenant_id Assignment

When any document is created, `set_tenant_id()` automatically sets:

- `tenant_id` = current user's tenant_id
- Skips system doctypes (User, Role, DocType, Tenant, Subscription, etc.)
- Administrator bypass (no tenant_id set)

### Query Filtering

`get_permission_query_conditions()` returns SQL WHERE clause:

```sql
-- For regular users:
(tenant_id = 'user_tenant_id' OR tenant_id = 'SYSTEM' OR tenant_id IS NULL)

-- For Administrator:
NULL (no filtering - sees everything)
```

## System DocTypes (Excluded from Tenant Isolation)

These DocTypes are shared across all tenants:

```python
system_doctypes = [
    'User', 'Role', 'DocType', 'DocField', 'DocPerm', 'Module Def',
    'Domain', 'Domain Settings', 'Tenant', 'Plan', 'Subscription Plan',
    'Subscription', 'Subscription Plan Detail', 'Customer',
    'Workspace', 'Workflow', 'Print Format', 'Email Template',
    'System Settings', 'Website Settings', 'Portal Settings',
    'Error Log', 'Activity Log', 'Version', 'Communication',
    'Comment', 'File', 'Custom Field'
]
```

## User Access Matrix

| User Type              | See Own Tenant Data | See SYSTEM Data | See All Data |
| ---------------------- | ------------------- | --------------- | ------------ |
| Tenant User            | ✅                  | ✅              | ❌           |
| Tenant Admin           | ✅                  | ✅              | ❌           |
| Platform Administrator | ✅                  | ✅              | ✅           |

## Key Files

| File                                        | Purpose                                                                     |
| ------------------------------------------- | --------------------------------------------------------------------------- |
| `saas_platform/doctype/tenant/tenant.py`    | Tenant business logic, auto-creation of Customer, Company, Subscription     |
| `saas_platform/doctype/tenant/tenant.json`  | Tenant DocType definition                                                   |
| `saas_platform/utils/tenant.py`             | Tenant isolation utilities (set_tenant_id, get_permission_query_conditions) |
| `saas_platform/hooks.py`                    | Frappe hooks for doc_events and permission_query_conditions                 |
| `saas_platform/utils/add_tenant_columns.py` | Migration utility to add tenant_id to all tables                            |
| `saas_platform/utils/add_custom_fields.py`  | Utility to add tenant_id Custom Fields                                      |

## ERPNext Integration

### Subscription Plan (ERPNext Built-in)

Uses ERPNext's native Subscription Plan DocType:

- `plan_name`: "Free Plan", "Pro Plan", etc.
- `item`: Link to Item DocType
- `cost`: Monthly/yearly cost
- `billing_interval`: Day/Week/Month/Year
- `currency`: System default currency

### Subscription (ERPNext Built-in)

Uses ERPNext's native Subscription DocType:

- `party_type`: "Customer"
- `party`: Link to Customer
- `plans`: Child table with Subscription Plans
- Manages trial periods, invoicing, renewals

## Example: Complete Tenant Data

```
Tenant: Acme Corporation
├── tenant_id: acme-corp-a1b2c3d4
├── subdomain: acme
├── admin_email: admin@acme.com
├── status: Trial
├── trial_expiry: 2025-12-28
│
├── Customer: Acme Corporation (tenant_id: SYSTEM)
│   └── For platform billing
│
├── Subscription: ACC-SUB-2025-00001 (tenant_id: SYSTEM)
│   ├── Party: Customer - Acme Corporation
│   ├── Status: Trialling
│   └── Plan: Free Plan
│
└── Company: Acme Corporation (tenant_id: acme-corp-a1b2c3d4)
    └── Tenant's own company for their accounting
        ├── Items (tenant_id: acme-corp-a1b2c3d4)
        ├── Sales Orders (tenant_id: acme-corp-a1b2c3d4)
        ├── Invoices (tenant_id: acme-corp-a1b2c3d4)
        └── ... all business data
```

## Security Considerations

1. **Row-Level Security**: All queries automatically filtered by tenant_id
2. **Administrator Bypass**: Only system Administrator can see all data
3. **SYSTEM tenant_id**: Platform data (subscriptions, billing) isolated from tenant data
4. **Custom Field Protection**: tenant_id fields are hidden, read-only, no-copy

## Future Enhancements

- [ ] Tenant-specific user management
- [ ] Subdomain-based routing
- [ ] Usage-based billing integration
- [ ] Tenant data export/import
- [ ] Cross-tenant reporting for administrators

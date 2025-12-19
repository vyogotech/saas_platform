"""
Tenant ID Migration Patch for saas_platform

Adds tenant_id column to ALL DocTypes using ALTER TABLE for performance.
This is a Frappe patch that runs during migration (bench migrate).

Usage:
    Add to patches.txt:
    saas_platform.patches.add_tenant_id_to_all_tables.execute
"""

import frappe


def execute():
    """Main patch execution - called by bench migrate"""
    print("\n" + "=" * 70)
    print("TENANT ID MIGRATION PATCH")
    print("=" * 70)

    # Get all DocTypes (including child tables)
    all_doctypes = frappe.get_all('DocType',
                                  # Exclude single DocTypes
                                  filters={'issingle': 0},
                                  fields=['name', 'istable'],
                                  order_by='name'
                                  )

    print(f"\n📋 Found {len(all_doctypes)} DocTypes to process")
    print(
        f"   (Including {sum(1 for dt in all_doctypes if dt.istable)} child tables)\n")

    success_count = 0
    skip_count = 0
    error_count = 0

    for doctype_info in all_doctypes:
        doctype_name = doctype_info.name
        try:
            result = add_tenant_id_column(doctype_name)
            if result == "added":
                success_count += 1
            elif result == "exists":
                skip_count += 1
        except Exception as e:
            print(f"\n❌ Error processing {doctype_name}: {str(e)}")
            error_count += 1

    # Summary
    print("\n" + "=" * 70)
    print("MIGRATION SUMMARY")
    print("=" * 70)
    print(f"✅ Added: {success_count}")
    print(f"⏭️  Skipped (already exists): {skip_count}")
    print(f"❌ Errors: {error_count}")
    print(f"📊 Total: {len(all_doctypes)}")
    print("=" * 70)

    if error_count > 0:
        frappe.log_error(
            "Tenant ID migration completed with errors", "Tenant Migration")

    frappe.db.commit()


def add_tenant_id_column(doctype_name):
    """
    Add tenant_id column using ALTER TABLE

    Returns:
        'added' if column was added
        'exists' if column already exists
    """
    table_name = f"tab{doctype_name}"

    # Check if column already exists
    columns = frappe.db.sql(f"""
        SHOW COLUMNS FROM `{table_name}` LIKE 'tenant_id'
    """, as_dict=True)

    if columns:
        return "exists"

    print(f"   ➕ Adding tenant_id to {doctype_name}...")

    # Add column with ALTER TABLE
    frappe.db.sql(f"""
        ALTER TABLE `{table_name}` 
        ADD COLUMN tenant_id VARCHAR(140) DEFAULT 'SYSTEM'
    """)

    # Add index for performance
    try:
        index_name = f"{table_name}_tenant_id_index"
        frappe.db.sql(f"""
            ALTER TABLE `{table_name}` 
            ADD INDEX `{index_name}` (tenant_id)
        """)
    except Exception as e:
        # Index might already exist, that's okay
        pass

    return "added"


if __name__ == '__main__':
    """Allow running as standalone script for testing"""
    import sys

    if len(sys.argv) > 1:
        site = sys.argv[1]
    else:
        site = 'dev.localhost'

    print(f"Initializing Frappe for site: {site}")
    frappe.init(site=site)
    frappe.connect()

    execute()

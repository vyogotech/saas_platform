"""Test tenant creation with Customer, Company, and Subscription"""
import frappe


def test_create_tenant():
    """Test creating a tenant - should auto-create Customer (SYSTEM), Company (tenant), and Subscription"""

    # List available Subscription Plans
    print("=== Available Subscription Plans ===")
    plans = frappe.get_all("Subscription Plan", fields=[
                           "name", "plan_name", "cost", "billing_interval"])
    if plans:
        for plan in plans:
            print(f"  - {plan.plan_name}: ${plan.cost}/{plan.billing_interval}")
    else:
        print("  No Subscription Plans found (will be created automatically)")

    # Create a test tenant
    print("\n=== Creating Test Tenant ===")
    # Create a test tenant with unique name using timestamp
    import time
    unique_suffix = str(int(time.time()))[-4:]

    tenant = frappe.get_doc({
        "doctype": "Tenant",
        "tenant_name": f"Test Corp {unique_suffix}",
        "subdomain": f"testcorp{unique_suffix}",
        "admin_email": f"admin{unique_suffix}@test.com",
        "status": "Active"
    })
    tenant.insert()
    frappe.db.commit()

    print(f"✅ Created Tenant: {tenant.name}")
    print(f"   tenant_id: {tenant.tenant_id}")
    print(f"   Subdomain: {tenant.subdomain}")
    print(f"   Status: {tenant.status}")
    print(f"   Trial Expiry: {tenant.trial_expiry}")

    # Check Subscription was created
    if tenant.subscription:
        subscription = frappe.get_doc("Subscription", tenant.subscription)
        print(f"   ✅ Subscription: {subscription.name}")
        print(f"      Party: {subscription.party_type} - {subscription.party}")
        print(f"      Status: {subscription.status}")
        if subscription.plans:
            for plan in subscription.plans:
                print(f"      Plan: {plan.plan} (qty: {plan.qty})")
    else:
        print(f"   ❌ No Subscription created")

    # Check Customer was created with SYSTEM tenant_id
    customer = frappe.get_all("Customer",
                              filters={"customer_name": [
                                  "like", f"{tenant.tenant_name}%"]},
                              fields=["name", "tenant_id"],
                              limit=1
                              )
    if customer:
        print(f"   ✅ Customer: {customer[0].name}")
        print(f"      tenant_id: {customer[0].tenant_id} (should be SYSTEM)")

    # Check Company was created with tenant's tenant_id
    companies = frappe.get_all("Company",
                               filters={"tenant_id": tenant.tenant_id},
                               fields=["name", "tenant_id"]
                               )
    if companies:
        for company in companies:
            print(f"   ✅ Company: {company.name}")
            print(f"      tenant_id: {company.tenant_id}")
    else:
        print(f"   ❌ No Company with tenant_id found")

    # Check Admin User was created with tenant's tenant_id
    admin_user = frappe.get_all("User",
                                filters={"email": tenant.admin_email},
                                fields=["name", "email",
                                        "tenant_id", "enabled"]
                                )
    if admin_user:
        user = admin_user[0]
        print(f"   ✅ Admin User: {user.email}")
        print(f"      tenant_id: {user.tenant_id}")
        print(f"      enabled: {user.enabled}")
    else:
        print(f"   ❌ No Admin User created")

    return tenant.name

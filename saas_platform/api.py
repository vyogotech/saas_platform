import frappe
from frappe.utils import add_days, nowdate
@frappe.whitelist(allow_guest=True)
def register_user(email, company, password, subdomain):
    # 1. Create Tenant Doc
    tenant = frappe.get_doc({
        'doctype': 'Tenant',
        'tenant_name': company,
        'admin_email': email,
        'subdomain': subdomain,
        'status': 'Trial',
        'trial_expiry': add_days(nowdate(), 14)
    })
    tenant.insert(ignore_permissions=True)

    # 2. Enqueue Background Job
    frappe.enqueue('saas_platform.tasks.provision_site', tenant=tenant.name, password=password)

    return {"success": True}

import subprocess
import frappe
from frappe.utils import  nowdate, add_days
def provision_site(tenant, password):
    doc = frappe.get_doc("Tenant", tenant)
    site_name = f"{doc.subdomain}.localhost"

    cmd = [
        "bench", "new-site", site_name,
        "--admin-password", password,
        "--install-app", "erpnext",
        "--install-app", "saas_platform"
    ]

    subprocess.run(cmd, cwd=frappe.get_bench_path())

    doc.site_name = site_name
    doc.status = "Active"
    doc.save()


def suspend_expired_trials():
    tenants = frappe.get_all("Tenant", filters={"status": "Trial"})
    for t in tenants:
        doc = frappe.get_doc("Tenant", t.name)
        if doc.trial_expiry < nowdate():
            suspend_tenant(doc.name)

def suspend_tenant(tenant_name):
    doc = frappe.get_doc("Tenant", tenant_name)
    subprocess.run(["bench", "--site", doc.site_name, "set-maintenance-mode", "on"])
    doc.status = "Suspended"
    doc.save()
    
    
def send_trial_warning_emails():
    today = nowdate()
    in_three_days = add_days(today, 3)
    in_one_day = add_days(today, 1)

    tenants = frappe.get_all("Tenant", fields=["name", "admin_email", "trial_expiry"])
    for t in tenants:
        if t.trial_expiry == in_three_days or t.trial_expiry == in_one_day:
            frappe.sendmail(
                recipients=[t.admin_email],
                subject="Your trial is expiring soon!",
                message=f"Dear user, your trial expires on {t.trial_expiry}. Please subscribe to continue."
            )    
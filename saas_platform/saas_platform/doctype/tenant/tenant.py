# Copyright (c) 2025, Asofi and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import uuid
from frappe.utils import nowdate, add_days


class Tenant(Document):
    def get_default_currency(self):
        """Get system default currency"""
        return frappe.db.get_single_value('Global Defaults', 'default_currency') or 'USD'

    def before_insert(self):
        """Generate unique tenant_id before insert"""
        if not self.tenant_id:
            # Generate tenant_id from tenant_name + uuid
            slug = self.tenant_name.lower().replace(' ', '-')[:20]
            unique_suffix = str(uuid.uuid4())[:8]
            self.tenant_id = f"{slug}-{unique_suffix}"
            frappe.log(f"Generated tenant_id: {self.tenant_id}")

    def validate(self):
        """Validate tenant data"""
        # Check subdomain uniqueness
        if self.is_new() or self.has_value_changed('subdomain'):
            existing = frappe.db.exists('Tenant', {
                'subdomain': self.subdomain,
                'name': ['!=', self.name]
            })
            if existing:
                frappe.throw(f"Subdomain '{self.subdomain}' is already taken")

        # Check admin_email uniqueness
        if self.is_new() or self.has_value_changed('admin_email'):
            existing = frappe.db.exists('Tenant', {
                'admin_email': self.admin_email,
                'name': ['!=', self.name]
            })
            if existing:
                frappe.throw(
                    f"Email '{self.admin_email}' is already registered")

        # Validate email format
        if self.admin_email and '@' not in self.admin_email:
            frappe.throw("Invalid email address")

    def after_insert(self):
        """Auto-create Customer, Company, Admin User, and Subscription after tenant creation"""
        frappe.log(
            f"Tenant {self.tenant_name} created with tenant_id: {self.tenant_id}")

        # 1. Create Customer (SYSTEM tenant_id - this is OUR customer for billing)
        customer_name = self.create_customer()

        # 2. Create default Company for the tenant (tenant's own company)
        self.create_company()

        # 3. Create or update admin user for the tenant
        self.setup_admin_user()

        # 4. Create Subscription with Free Plan (links Customer to Plan)
        self.create_subscription(customer_name)

        # Save changes
        self.save()

    def create_customer(self):
        """Create ERPNext Customer for billing (tenant_id = SYSTEM)"""
        try:
            customer_name = f"{self.tenant_name}"

            # Check if customer with this name already exists
            if frappe.db.exists("Customer", customer_name):
                counter = 1
                while frappe.db.exists("Customer", f"{customer_name} {counter}"):
                    counter += 1
                customer_name = f"{customer_name} {counter}"

            customer = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": customer_name,
                "customer_type": "Company",
                "customer_group": "Commercial",
                "territory": "All Territories",
                "default_currency": self.get_default_currency(),
            })
            customer.insert(ignore_permissions=True)

            # Set tenant_id = SYSTEM (this is OUR customer, not tenant's data)
            frappe.db.set_value("Customer", customer.name,
                                "tenant_id", "SYSTEM", update_modified=False)
            frappe.db.commit()

            frappe.log(
                f"Created customer: {customer.name} for tenant: {self.tenant_id}")
            return customer.name

        except Exception as e:
            frappe.log_error(
                f"Failed to create customer for tenant {self.tenant_id}: {str(e)}")
            frappe.throw(f"Failed to create customer: {str(e)}")

    def create_company(self):
        """Create ERPNext Company for tenant's own use"""
        try:
            company_name = self.tenant_name

            # Check if company with this name already exists
            if frappe.db.exists("Company", company_name):
                counter = 1
                while frappe.db.exists("Company", f"{company_name} {counter}"):
                    counter += 1
                company_name = f"{company_name} {counter}"

            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": company_name,
                "abbr": self.get_company_abbr(),
                "default_currency": "USD",
                "country": "United States",
            })
            company.insert(ignore_permissions=True)

            # Set tenant_id = tenant's ID (this is tenant's company)
            frappe.db.set_value(
                "Company", company.name, "tenant_id", self.tenant_id, update_modified=False)
            frappe.db.commit()

            frappe.log(
                f"Created company: {company.name} for tenant: {self.tenant_id}")

        except Exception as e:
            frappe.log_error(
                f"Failed to create company for tenant {self.tenant_id}: {str(e)}")
            frappe.throw(f"Failed to create company: {str(e)}")

    def setup_admin_user(self):
        """Create or update admin user for this tenant"""
        try:
            if frappe.db.exists("User", self.admin_email):
                # User exists - just set tenant_id
                frappe.db.set_value(
                    "User", self.admin_email, "tenant_id", self.tenant_id, update_modified=False)
                frappe.db.commit()
                frappe.log(
                    f"Updated existing user {self.admin_email} with tenant_id: {self.tenant_id}")
            else:
                # Create new user
                user = frappe.get_doc({
                    "doctype": "User",
                    "email": self.admin_email,
                    "first_name": self.tenant_name,
                    "enabled": 1,
                    "user_type": "System User",
                    "send_welcome_email": 0,  # Don't send email during creation
                    "roles": [
                        {"role": "System Manager"},
                        {"role": "Accounts Manager"},
                        {"role": "Sales Manager"},
                        {"role": "Purchase Manager"},
                        {"role": "Stock Manager"},
                    ]
                })
                user.insert(ignore_permissions=True)

                # Set tenant_id
                frappe.db.set_value(
                    "User", user.name, "tenant_id", self.tenant_id, update_modified=False)
                frappe.db.commit()

                frappe.log(
                    f"Created admin user: {self.admin_email} for tenant: {self.tenant_id}")

        except Exception as e:
            frappe.log_error(
                f"Failed to setup admin user for tenant {self.tenant_id}: {str(e)}")
            # Don't throw - user can be set up later

    def create_subscription(self, customer_name):
        """Create Subscription linking Customer to Free Plan"""
        if self.subscription:
            return  # Subscription already exists

        try:
            # Ensure Free Subscription Plan exists
            if not frappe.db.exists("Subscription Plan", "Free Plan"):
                self.create_free_subscription_plan()

            # Create Subscription
            subscription = frappe.get_doc({
                "doctype": "Subscription",
                "party_type": "Customer",
                "party": customer_name,
                "start_date": nowdate(),
                "trial_period_start": nowdate(),
                "trial_period_end": add_days(nowdate(), 14),
                "generate_invoice_at": "End of the current subscription period",
                "plans": [{
                    "plan": "Free Plan",
                    "qty": 1
                }]
            })
            subscription.insert(ignore_permissions=True)

            # Set tenant_id = SYSTEM (this is OUR subscription record)
            frappe.db.set_value("Subscription", subscription.name,
                                "tenant_id", "SYSTEM", update_modified=False)
            frappe.db.commit()

            self.subscription = subscription.name
            self.trial_expiry = add_days(nowdate(), 14)
            self.status = "Trial"

            frappe.log(
                f"Created subscription: {subscription.name} for tenant: {self.tenant_id}")

        except Exception as e:
            frappe.log_error(
                f"Failed to create subscription for tenant {self.tenant_id}: {str(e)}")
            # Don't throw - subscription can be created later

    def create_free_subscription_plan(self):
        """Create a Free Subscription Plan if it doesn't exist"""
        try:
            default_currency = self.get_default_currency()
            plan = frappe.get_doc({
                "doctype": "Subscription Plan",
                "plan_name": "Free Plan",
                "item": "Free Plan Service",  # This needs to be an Item
                "cost": 0,
                "billing_interval": "Month",
                "billing_interval_count": 1,
                "currency": default_currency,
                "price_determination": "Fixed Rate"
            })

            # First create the Item if it doesn't exist
            if not frappe.db.exists("Item", "Free Plan Service"):
                item = frappe.get_doc({
                    "doctype": "Item",
                    "item_code": "Free Plan Service",
                    "item_name": "Free Plan Service",
                    "item_group": "Services",
                    "stock_uom": "Nos",
                    "is_stock_item": 0,
                    "is_sales_item": 1
                })
                item.insert(ignore_permissions=True)

            plan.insert(ignore_permissions=True)
            frappe.db.commit()
            frappe.log(f"Created Free Subscription Plan")
        except Exception as e:
            frappe.log_error(
                f"Failed to create Free Subscription Plan: {str(e)}")

    def get_company_abbr(self):
        """Generate company abbreviation from tenant name"""
        # Get first letters of each word, max 5 chars
        words = self.tenant_name.split()
        abbr = ''.join([w[0].upper() for w in words if w])[:5]

        # Ensure uniqueness
        base_abbr = abbr
        counter = 1
        while frappe.db.exists('Company', {'abbr': abbr}):
            abbr = f"{base_abbr}{counter}"
            counter += 1

        return abbr

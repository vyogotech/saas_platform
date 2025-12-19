# Copyright (c) 2025, Asofi and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Plan(Document):
    def validate(self):
        """Validate plan data"""
        # Ensure Free plan has 0 price
        if self.plan_type == "Free" and self.price and self.price > 0:
            frappe.throw("Free plan must have price = 0")

        # Ensure paid plans have price
        if self.plan_type in ["Business Basic", "Business Pro"] and not self.price:
            frappe.throw(f"{self.plan_type} must have a price")

    def before_insert(self):
        """Set tenant_id to SYSTEM for shared plans"""
        if not self.tenant_id:
            self.tenant_id = "SYSTEM"

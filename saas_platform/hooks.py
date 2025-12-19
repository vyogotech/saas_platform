app_name = "saas_platform"
app_title = "Saas Platform"
app_publisher = "Vyogo Technologies PTY Ltd"
app_description = "Saas Platform"
app_email = "dev@vyogo.tech"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "saas_platform",
# 		"logo": "/assets/saas_platform/logo.png",
# 		"title": "Saas Platform",
# 		"route": "/saas_platform",
# 		"has_permission": "saas_platform.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/saas_platform/css/saas_platform.css"
# app_include_js = "/assets/saas_platform/js/saas_platform.js"

# include js, css files in header of web template
# web_include_css = "/assets/saas_platform/css/saas_platform.css"
# web_include_js = "/assets/saas_platform/js/saas_platform.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "saas_platform/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "saas_platform/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "saas_platform.utils.jinja_methods",
# 	"filters": "saas_platform.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "saas_platform.install.before_install"
# after_install = "saas_platform.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "saas_platform.uninstall.before_uninstall"
# after_uninstall = "saas_platform.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "saas_platform.utils.before_app_install"
after_install = "saas_platform.utils.tenant.setup_user_tenant"
after_app_install = "saas_platform.patches.add_tenant_id_to_all_tables.execute"
# Also ensure setup runs after app install to catch any missed initialization
after_app_install = [
    "saas_platform.patches.add_tenant_id_to_all_tables.execute",
    "saas_platform.utils.tenant.setup_user_tenant"
]

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "saas_platform.utils.before_app_uninstall"
# after_app_uninstall = "saas_platform.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "saas_platform.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# Apply tenant isolation to ALL DocTypes
# permission_query_conditions = {
#     "*": "saas_platform.permissions.get_tenant_query",
# }

# has_permission = {
#     "*": "saas_platform.permissions.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# Auto-populate tenant_id on all documents before insert
doc_events = {
    "*": {
        "before_insert": "saas_platform.utils.set_tenant_id",
    }
}

# Post-login hook to set tenant_id in session
on_session_creation = "saas_platform.utils.tenant.on_session_creation"

# # Permission Query - Filter data by tenant_id (except for Administrator)
permission_query_conditions = {
    "*": "saas_platform.utils.tenant.get_permission_query_conditions"
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"saas_platform.tasks.all"
# 	],
# 	"daily": [
# 		"saas_platform.tasks.daily"
# 	],
# 	"hourly": [
# 		"saas_platform.tasks.hourly"
# 	],
# 	"weekly": [
# 		"saas_platform.tasks.weekly"
# 	],
# 	"monthly": [
# 		"saas_platform.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "saas_platform.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "saas_platform.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "saas_platform.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["saas_platform.utils.before_request"]
# after_request = ["saas_platform.utils.after_request"]

# Job Events
# ----------
# before_job = ["saas_platform.utils.before_job"]
# after_job = ["saas_platform.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"saas_platform.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }


website_route_rules = [
    {'from_route': '/frontend/<path:app_path>', 'to_route': 'frontend'},]
# Fixtures
# --------
# No fixtures needed - using ERPNext's Subscription Plan

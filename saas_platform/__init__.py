__version__ = "0.0.1"

# Tenant isolation patches. No try/except: if these fail to install, tenant
# queries would run unfiltered, so the app must fail loudly instead.
from saas_platform.utils.sql_rewriter import install_db_patch
from saas_platform.utils.naming import patch_frappe_naming

install_db_patch()
patch_frappe_naming()



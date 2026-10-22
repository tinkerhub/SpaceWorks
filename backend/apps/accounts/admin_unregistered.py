"""Remove unused admin pages while preserving operational security controls.

SpaceWorks authorization uses MakerspaceMembership + MakerspaceRole
(apps/accounts/rbac.py), so Django auth Groups are never read. Axes AccessLog has
no SpaceWorks reader; AccessFailureLog is only written when
AXES_ENABLE_ACCESS_FAILURE_LOG is on, which SpaceWorks never sets. Keep
AccessAttempt for unlocking accounts and SimpleJWT OutstandingToken/BlacklistedToken
admins for manual per-token revocation.
"""

from axes.models import AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.models import Group

admin.site.unregister(Group)
admin.site.unregister(AccessLog)
admin.site.unregister(AccessFailureLog)

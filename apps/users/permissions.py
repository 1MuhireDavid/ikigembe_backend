from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """
    Allow access to users with role == 'Admin'.
    Also passes for Django staff/superusers so existing admin accounts
    are not locked out after the role field is introduced.
    """
    message = 'Admin access required.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (
                user.role == 'Admin'
                or user.is_staff
                or user.is_superuser
            )
        )


class IsProducerRole(BasePermission):
    """
    Allow access only to users with role == 'Producer'.
    """
    message = 'Producer access required.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == 'Producer'
        )


class IsAdminOrProducerRole(BasePermission):
    """
    Allow access to users with role == 'Admin' or role == 'Producer'.
    """
    message = 'Admin or Producer access required.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('Admin', 'Producer')
        )

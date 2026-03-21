from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """
    Allow access only to users with role == 'Admin'.
    Returns 403 Forbidden for any other authenticated user.
    """
    message = 'Admin access required.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == 'Admin'
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

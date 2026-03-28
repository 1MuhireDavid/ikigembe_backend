from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    GoogleAuthView,
    TokenRefreshView,
    MeView,
    LogoutView,
    ChangePasswordView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='auth-register'),
    path('login/', LoginView.as_view(), name='auth-login'),
    path('google/', GoogleAuthView.as_view(), name='auth-google'),
    path('token/refresh/', TokenRefreshView.as_view(), name='auth-token-refresh'),
    path('me/', MeView.as_view(), name='auth-me'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('change-password/', ChangePasswordView.as_view(), name='auth-change-password'),
]

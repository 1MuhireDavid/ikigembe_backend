from django.urls import path
from .views import InitiatePaymentView, PaymentStatusView, PaymentHistoryView, PawapayWebhookView

urlpatterns = [
    path('initiate/', InitiatePaymentView.as_view(), name='payment-initiate'),
    path('history/', PaymentHistoryView.as_view(), name='payment-history'),
    path('<str:deposit_id>/status/', PaymentStatusView.as_view(), name='payment-status'),
    path('webhook/pawapay/', PawapayWebhookView.as_view(), name='payment-webhook-pawapay'),
]

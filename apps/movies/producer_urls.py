from django.urls import path
from .producer_views import ProducerMyMoviesView, ProducerWalletView, ProducerWithdrawalsView

urlpatterns = [
    path('movies/', ProducerMyMoviesView.as_view(), name='producer-my-movies'),
    path('wallet/', ProducerWalletView.as_view(), name='producer-wallet'),
    path('withdrawals/', ProducerWithdrawalsView.as_view(), name='producer-withdrawals'),
]

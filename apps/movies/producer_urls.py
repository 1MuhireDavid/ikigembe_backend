from django.urls import path
from .producer_views import (
    ProducerMyMoviesView,
    ProducerMovieDetailView,
    ProducerWalletView,
    ProducerWithdrawalsView,
)

urlpatterns = [
    path('movies/', ProducerMyMoviesView.as_view(), name='producer-my-movies'),
    path('movies/<int:id>/', ProducerMovieDetailView.as_view(), name='producer-movie-detail'),
    path('wallet/', ProducerWalletView.as_view(), name='producer-wallet'),
    path('withdrawals/', ProducerWithdrawalsView.as_view(), name='producer-withdrawals'),
]

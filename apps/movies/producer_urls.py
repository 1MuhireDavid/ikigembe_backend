from django.urls import path
from .producer_views import ProducerMyMoviesView

urlpatterns = [
    path('movies/', ProducerMyMoviesView.as_view(), name='producer-my-movies'),
]

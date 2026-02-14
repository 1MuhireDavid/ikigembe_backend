from django.urls import path
from .views import (
    DiscoverMoviesView,
    PopularMoviesView,
    NowPlayingMoviesView,
    TopRatedMoviesView,
    UpcomingMoviesView,
    MovieDetailView,
    MovieVideosView,
    MovieImagesView,
    MovieStreamView,
    MovieTrailerView
)

urlpatterns = [
    # Discovery & Lists
    path('discover/', DiscoverMoviesView.as_view(), name='discover-movies'),
    path('popular/', PopularMoviesView.as_view(), name='popular-movies'),
    path('now-playing/', NowPlayingMoviesView.as_view(), name='now-playing-movies'),
    path('top-rated/', TopRatedMoviesView.as_view(), name='top-rated-movies'),
    path('upcoming/', UpcomingMoviesView.as_view(), name='upcoming-movies'),
    
    # Movie Details
    path('<int:id>/', MovieDetailView.as_view(), name='movie-detail'),
    path('<int:id>/videos/', MovieVideosView.as_view(), name='movie-videos'),
    path('<int:id>/images/', MovieImagesView.as_view(), name='movie-images'),
    
    # Video Streaming (NEW)
    path('<int:id>/stream/', MovieStreamView.as_view(), name='movie-stream'),  # Full movie
    path('<int:id>/trailer/', MovieTrailerView.as_view(), name='movie-trailer'),  # Free trailer
]
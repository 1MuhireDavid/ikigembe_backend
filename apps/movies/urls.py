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
    MovieTrailerView,
    MovieCreateView,
    InitiateMultipartUploadView,
    SignMultipartUploadPartView,
    CompleteMultipartUploadView,
    AbortMultipartUploadView
)

urlpatterns = [
    # Discovery & Lists
    path('discover/', DiscoverMoviesView.as_view(), name='discover-movies'),
    path('popular/', PopularMoviesView.as_view(), name='popular-movies'),
    path('now-playing/', NowPlayingMoviesView.as_view(), name='now-playing-movies'),
    path('top-rated/', TopRatedMoviesView.as_view(), name='top-rated-movies'),
    path('upcoming/', UpcomingMoviesView.as_view(), name='upcoming-movies'),
    
    # Movie Details
    path('create/', MovieCreateView.as_view(), name='movie-create'),
    
    # Multipart Upload
    path('upload/initiate/', InitiateMultipartUploadView.as_view(), name='upload-initiate'),
    path('upload/sign-part/', SignMultipartUploadPartView.as_view(), name='upload-sign-part'),
    path('upload/complete/', CompleteMultipartUploadView.as_view(), name='upload-complete'),
    path('upload/abort/', AbortMultipartUploadView.as_view(), name='upload-abort'),

    path('<int:id>/', MovieDetailView.as_view(), name='movie-detail'),
    path('<int:id>/videos/', MovieVideosView.as_view(), name='movie-videos'),
    path('<int:id>/images/', MovieImagesView.as_view(), name='movie-images'),
    
    # Video Streaming (NEW)
    path('<int:id>/stream/', MovieStreamView.as_view(), name='movie-stream'),  # Full movie
    path('<int:id>/trailer/', MovieTrailerView.as_view(), name='movie-trailer'),  # Free trailer
]
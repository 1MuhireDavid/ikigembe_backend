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
    MovieTranscodeView,
    MovieCreateView,
    MovieUpdateView,
    MovieDeleteView,
    InitiateMultipartUploadView,
    SignMultipartUploadPartView,
    CompleteMultipartUploadView,
    AbortMultipartUploadView,
)

urlpatterns = [
    # ── Discovery & Lists ──────────────────────────────────────────────
    path('discover/', DiscoverMoviesView.as_view(), name='discover-movies'),
    path('popular/', PopularMoviesView.as_view(), name='popular-movies'),
    path('now-playing/', NowPlayingMoviesView.as_view(), name='now-playing-movies'),
    path('top-rated/', TopRatedMoviesView.as_view(), name='top-rated-movies'),
    path('upcoming/', UpcomingMoviesView.as_view(), name='upcoming-movies'),

    # ── Movie CRUD (admin) ─────────────────────────────────────────────
    path('create/', MovieCreateView.as_view(), name='movie-create'),
    path('<int:id>/update/', MovieUpdateView.as_view(), name='movie-update'),
    path('<int:id>/delete/', MovieDeleteView.as_view(), name='movie-delete'),

    # ── Movie details & media ──────────────────────────────────────────
    path('<int:id>/', MovieDetailView.as_view(), name='movie-detail'),
    path('<int:id>/videos/', MovieVideosView.as_view(), name='movie-videos'),
    path('<int:id>/images/', MovieImagesView.as_view(), name='movie-images'),
    path('<int:id>/stream/', MovieStreamView.as_view(), name='movie-stream'),
    path('<int:id>/trailer/', MovieTrailerView.as_view(), name='movie-trailer'),
    path('<int:id>/transcode/', MovieTranscodeView.as_view(), name='movie-transcode'),

    # ── S3 Multipart Upload (admin) ────────────────────────────────────
    path('upload/initiate/', InitiateMultipartUploadView.as_view(), name='upload-initiate'),
    path('upload/sign-part/', SignMultipartUploadPartView.as_view(), name='upload-sign-part'),
    path('upload/complete/', CompleteMultipartUploadView.as_view(), name='upload-complete'),
    path('upload/abort/', AbortMultipartUploadView.as_view(), name='upload-abort'),
]
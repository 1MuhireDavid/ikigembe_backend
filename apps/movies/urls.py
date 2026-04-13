from django.urls import path
from .views import (
    DiscoverMoviesView,
    MovieSearchView,
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
    MovieHlsStatusView,
    MovieCreateView,
    MovieUpdateView,
    MovieDeleteView,
    SubtitleListView,
    InitiateMultipartUploadView,
    SignMultipartUploadPartView,
    CompleteMultipartUploadView,
    AbortMultipartUploadView,
    MyListView,
    ContinueWatchingView,
    WatchProgressView,
    ProducerListView,
    MoviesByProducerView,
)

urlpatterns = [
    # ── Browse by Producer ─────────────────────────────────────────────
    path('producers/', ProducerListView.as_view(), name='producer-list'),
    path('producers/<int:producer_id>/', MoviesByProducerView.as_view(), name='movies-by-producer'),

    # ── Discovery & Lists ──────────────────────────────────────────────
    path('discover/', DiscoverMoviesView.as_view(), name='discover-movies'),
    path('search/', MovieSearchView.as_view(), name='movie-search'),
    path('popular/', PopularMoviesView.as_view(), name='popular-movies'),
    path('now-playing/', NowPlayingMoviesView.as_view(), name='now-playing-movies'),
    path('top-rated/', TopRatedMoviesView.as_view(), name='top-rated-movies'),
    path('upcoming/', UpcomingMoviesView.as_view(), name='upcoming-movies'),

    # ── Viewer: My List & Continue Watching ───────────────────────────
    path('my-list/', MyListView.as_view(), name='my-list'),
    path('continue-watching/', ContinueWatchingView.as_view(), name='continue-watching'),

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
    path('<int:id>/hls-status/', MovieHlsStatusView.as_view(), name='movie-hls-status'),
    path('<int:id>/progress/', WatchProgressView.as_view(), name='movie-progress'),
    path('<int:id>/subtitles/', SubtitleListView.as_view(), name='movie-subtitles'),

    # ── S3 Multipart Upload (admin) ────────────────────────────────────
    path('upload/initiate/', InitiateMultipartUploadView.as_view(), name='upload-initiate'),
    path('upload/sign-part/', SignMultipartUploadPartView.as_view(), name='upload-sign-part'),
    path('upload/complete/', CompleteMultipartUploadView.as_view(), name='upload-complete'),
    path('upload/abort/', AbortMultipartUploadView.as_view(), name='upload-abort'),
]
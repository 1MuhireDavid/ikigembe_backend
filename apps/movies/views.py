from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.authentication import SessionAuthentication
from apps.users.permissions import IsAdminRole
from django.utils import timezone
from django.conf import settings
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from apps.payments.models import Payment
from .emails import send_new_movie_email
from .models import Movie, WatchProgress
from .serializers import (
    MovieSerializer,
    MovieDetailSerializer,
    MovieVideoAccessSerializer,
    MovieCreateSerializer,
    MyListMovieSerializer,
    WatchProgressSerializer,
)
import boto3
import uuid
import os

# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

_PAGE_PARAM = OpenApiParameter('page', OpenApiTypes.INT, description='Page number (default: 1)', required=False)
_SORT_PARAM = OpenApiParameter(
    'sort_by', OpenApiTypes.STR,
    description='Sort order: popularity.desc | release_date.desc | rating.desc',
    required=False,
    enum=['popularity.desc', 'release_date.desc', 'rating.desc'],
)

_PAGINATED_RESPONSE = inline_serializer(
    name='PaginatedMovieList',
    fields={
        'page': drf_serializers.IntegerField(),
        'results': MovieSerializer(many=True),
        'total_results': drf_serializers.IntegerField(),
        'total_pages': drf_serializers.IntegerField(),
    }
)


def _paginate(queryset, request):
    """Helper: paginate a queryset and return (page, page_size, slice)."""
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    page_size = 20
    start = (page - 1) * page_size
    total = queryset.count()
    return page, total, queryset[start:start + page_size]


# ─────────────────────────────────────────────
# Discovery / List endpoints
# ─────────────────────────────────────────────

class DiscoverMoviesView(APIView):
    """General movie discovery endpoint"""
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='page',
                description='Page number for pagination (default: 1)',
                required=False,
                type=OpenApiTypes.INT,
                location='query'
            ),
            OpenApiParameter(
                name='sort_by',
                description='Sort movies by: popularity.desc (default), release_date.desc, or rating.desc',
                required=False,
                type=OpenApiTypes.STR,
                location='query'
            ),
        ],
        tags=['Movies'],
        summary='Discover movies',
        description='Get a list of active movies with optional sorting and pagination.',
    )
    def get(self, request):
        sort_by = request.GET.get('sort_by', 'popularity.desc')
        movies = Movie.objects.filter(is_active=True)

        order_map = {
            'popularity.desc': '-views',
            'release_date.desc': '-release_date',
            'rating.desc': '-rating',
        }
        movies = movies.order_by(order_map.get(sort_by, '-views'))

        page, total, movies_page = _paginate(movies, request)
        serializer = MovieSerializer(movies_page, many=True)

        return Response({
            'page': page,
            'results': serializer.data,
            'total_results': total,
            'total_pages': (total + 19) // 20,
        })


class MovieSearchView(APIView):
    """Search movies by title, overview, genre, or cast."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='q',
                description='Search term — matches title, overview, genres, or cast',
                required=True,
                type=OpenApiTypes.STR,
                location='query',
            ),
            _PAGE_PARAM,
        ],
        tags=['Movies'],
        summary='Search movies',
        description='Search active movies by title, overview, genre, or cast member. Results are ordered by popularity.',
        responses={
            200: _PAGINATED_RESPONSE,
            400: OpenApiResponse(description='Missing or blank search term'),
        },
    )
    def get(self, request):
        q = request.GET.get('q', '').strip()
        if not q:
            return Response({'error': 'Search term "q" is required.'}, status=status.HTTP_400_BAD_REQUEST)

        movies = Movie.objects.filter(
            Q(title__icontains=q) |
            Q(overview__icontains=q) |
            Q(genres__icontains=q) |
            Q(cast__icontains=q),
            is_active=True,
        ).order_by('-views')

        page, total, movies_page = _paginate(movies, request)
        return Response({
            'page': page,
            'results': MovieSerializer(movies_page, many=True).data,
            'total_results': total,
            'total_pages': (total + 19) // 20,
        })


class PopularMoviesView(APIView):
    """Most viewed movies"""
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='page',
                description='Page number for pagination (default: 1)',
                required=False,
                type=OpenApiTypes.INT,
                location='query'
            ),
        ],
        tags=['Movies'],
        summary='Get popular movies',
        description='Get a list of the most viewed movies.',
    )
    def get(self, request):
        movies = Movie.objects.filter(is_active=True).order_by('-views')
        page, total, movies_page = _paginate(movies, request)
        return Response({
            'page': page,
            'results': MovieSerializer(movies_page, many=True).data,
            'total_results': total,
            'total_pages': (total + 19) // 20,
        })


class NowPlayingMoviesView(APIView):
    """Recently added movies"""    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='page',
                description='Page number for pagination (default: 1)',
                required=False,
                type=OpenApiTypes.INT,
                location='query'
            ),
        ],
        tags=['Movies'],
        summary='Get now playing movies',
        description='Get a list of recently added movies.',
    )
    def get(self, request):
        movies = Movie.objects.filter(is_active=True).order_by('-created_at')
        page, total, movies_page = _paginate(movies, request)
        return Response({
            'page': page,
            'results': MovieSerializer(movies_page, many=True).data,
            'total_results': total,
            'total_pages': (total + 19) // 20,
        })


class TopRatedMoviesView(APIView):
    """Highest rated movies"""
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='page',
                description='Page number for pagination (default: 1)',
                required=False,
                type=OpenApiTypes.INT,
                location='query'
            ),
        ],
        tags=['Movies'],
        summary='Get top rated movies',
        description='Get a list of the highest rated movies (rating >= 4.0).',
    )
    def get(self, request):
        movies = Movie.objects.filter(is_active=True, rating__gte=4.0).order_by('-rating')
        page, total, movies_page = _paginate(movies, request)
        return Response({
            'page': page,
            'results': MovieSerializer(movies_page, many=True).data,
            'total_results': total,
            'total_pages': (total + 19) // 20,
        })


class UpcomingMoviesView(APIView):
    """Movies with future release dates"""
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='page',
                description='Page number for pagination (default: 1)',
                required=False,
                type=OpenApiTypes.INT,
                location='query'
            ),
        ],
        tags=['Movies'],
        summary='Get upcoming movies',
        description='Get a list of movies with future release dates, sorted by release date.',
    )
    def get(self, request):
        today = timezone.now().date()
        movies = Movie.objects.filter(is_active=True, release_date__gte=today).order_by('release_date')
        page, total, movies_page = _paginate(movies, request)
        return Response({
            'page': page,
            'results': MovieSerializer(movies_page, many=True).data,
            'total_results': total,
            'total_pages': (total + 19) // 20,
        })


# ─────────────────────────────────────────────
# Movie Detail
# ─────────────────────────────────────────────

class MovieDetailView(APIView):
    """Detailed movie information - includes trailer"""
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='id',
                description='Movie ID',
                required=True,
                type=OpenApiTypes.INT,
                location='path'
            ),
        ],
        tags=['Movies'],
        summary='Get movie details',
        description='Get detailed information about a specific movie including title, description, rating, cast, etc.',
    )
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
            return Response(MovieDetailSerializer(movie).data)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────
# Media endpoints
# ─────────────────────────────────────────────

class MovieVideosView(APIView):
    """
    Get video information for a movie.
    Returns trailer (always accessible) and full video info.
    """
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='id',
                description='Movie ID',
                required=True,
                type=OpenApiTypes.INT,
                location='path'
            ),
        ],
        tags=['Movies'],
        summary='Get movie videos',
        description='Get video URLs and metadata for a movie (trailer and full movie if authenticated).',
    )
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        videos = []
        if movie.trailer_file:
            videos.append({
                'url': movie.trailer_url,
                'name': f'{movie.title} - Trailer',
                'type': 'Trailer',
                'site': 'Local',
                'duration_seconds': movie.trailer_duration_seconds,
                'is_free': True,
            })
        if movie.video_file:
            videos.append({
                'url': movie.video_url,
                'name': f'{movie.title} - Full Movie',
                'type': 'Full Movie',
                'site': 'Local',
                'duration_minutes': movie.duration_minutes,
                'requires_payment': True,
                'price': movie.price,
            })

        return Response({'id': movie.id, 'results': videos})


class MovieStreamView(APIView):
    """Get full-movie streaming URL — requires authentication and a completed payment."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Movies - Media'],
        summary='Stream full movie',
        description=(
            'Returns the streaming URL (HLS or MP4 fallback) for a purchased movie '
            'and increments its view counter. '
            'Requires a completed payment for the movie.'
        ),
        responses={
            200: MovieVideoAccessSerializer,
            403: OpenApiResponse(description='Movie not purchased'),
            404: OpenApiResponse(description='Movie not found'),
        },
    )
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        # Payment gate: verify the user has purchased this movie.
        has_access = Payment.objects.filter(
            user=request.user, movie=movie, status='Completed'
        ).exists()
        if not has_access:
            return Response(
                {'error': 'Purchase required to stream this movie.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        movie.increment_views()
        serializer = MovieVideoAccessSerializer(movie, context={'request': request})
        if movie.hls_status == 'ready' and movie.hls_url:
            return Response({
                'movie': serializer.data,
                'stream_url': movie.hls_url,
                'stream_type': 'hls',
                'hls_status': movie.hls_status,
                'fallback_url': movie.video_url,
            })
        return Response({
            'movie': serializer.data,
            'stream_url': movie.video_url,
            'stream_type': 'mp4',
            'hls_status': movie.hls_status,
            'fallback_url': None,
        })


class MovieTranscodeView(APIView):
    """Trigger HLS transcoding for a movie (admin only)."""
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - Media'],
        summary='Trigger HLS transcoding',
        description=(
            'Starts HLS adaptive bitrate transcoding for a movie in a background thread. '
            'Returns immediately with status 202. Poll the movie detail or stream endpoint '
            'to check `hls_status` (processing → ready / failed).'
        ),
        responses={
            202: inline_serializer(
                name='TranscodeResponse',
                fields={'status': drf_serializers.CharField(), 'hls_status': drf_serializers.CharField()}
            ),
            400: OpenApiResponse(description='Movie has no video file'),
            404: OpenApiResponse(description='Movie not found'),
            409: OpenApiResponse(description='Transcoding already in progress'),
        },
    )
    def post(self, request, id):
        try:
            movie = Movie.objects.get(id=id)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        if not movie.video_file:
            return Response({'error': 'Movie has no video file'}, status=status.HTTP_400_BAD_REQUEST)

        if movie.hls_status == 'processing':
            return Response({'error': 'Transcoding already in progress'}, status=status.HTTP_409_CONFLICT)

        from .transcoding import start_hls_transcode
        start_hls_transcode(movie.id)
        return Response(
            {'status': 'transcoding_started', 'hls_status': 'processing'},
            status=status.HTTP_202_ACCEPTED,
        )


class MovieTrailerView(APIView):
    """Get free trailer streaming URL"""

    @extend_schema(
        tags=['Movies - Media'],
        summary='Stream trailer',
        description='Returns the free trailer streaming URL for a movie.',
        responses={
            200: inline_serializer(
                name='TrailerResponse',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'title': drf_serializers.CharField(),
                    'stream_url': drf_serializers.URLField(),
                    'duration_seconds': drf_serializers.IntegerField(),
                    'is_free': drf_serializers.BooleanField(),
                }
            ),
            404: OpenApiResponse(description='Movie or trailer not found'),
        },
    )
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        if not movie.trailer_file:
            return Response(
                {'error': 'Trailer not available for this movie'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            'id': movie.id,
            'title': movie.title,
            'stream_url': movie.trailer_url,
            'duration_seconds': movie.trailer_duration_seconds,
            'is_free': True,
        })


class MovieImagesView(APIView):
    """Get image URLs for a movie"""

    @extend_schema(
        tags=['Movies - Media'],
        summary='Get movie images',
        description='Returns backdrop and poster (thumbnail) URLs for a movie.',
        responses={
            200: inline_serializer(
                name='MovieImages',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'backdrops': drf_serializers.ListField(child=drf_serializers.DictField()),
                    'posters': drf_serializers.ListField(child=drf_serializers.DictField()),
                }
            ),
            404: OpenApiResponse(description='Movie not found'),
        },
    )
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'id': movie.id,
            'backdrops': [{'file_path': movie.backdrop_url, 'width': 1280, 'height': 720}] if movie.backdrop_url else [],
            'posters': [{'file_path': movie.thumbnail_url, 'width': 300, 'height': 450}],
        })


# ─────────────────────────────────────────────
# Movie CRUD — Admin only
# ─────────────────────────────────────────────

class MovieCreateView(APIView):
    """
    Create a new movie with file uploads.
    Send as multipart/form-data. Requires admin auth.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - Admin'],
        summary='Create a new movie',
        description=(
            'Upload a new movie with all its media files in one request.\n\n'
            'Send the request as **multipart/form-data**.\n\n'
            '**Required:** `title`, `overview`, `release_date`, `thumbnail`, `video_file`\n\n'
            '**Optional:** `backdrop`, `trailer_file`, `price`, `duration_minutes`, '
            '`trailer_duration_seconds`, `cast`, `genres`, `producer`, `is_active`, `has_free_preview`\n\n'
            '`cast` and `genres` — send as a JSON array string, e.g. `["Action", "Drama"]`'
        ),
        request={
            'multipart/form-data': MovieCreateSerializer,
        },
        responses={
            201: MovieDetailSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Admin access required'),
        },
        examples=[
            OpenApiExample(
                'Example — Kigali Story',
                value={
                    'title': 'Kigali Story',
                    'overview': 'A drama set in post-genocide Rwanda.',
                    'release_date': '2024-06-01',
                    'price': 1000,
                    'duration_minutes': 112,
                    'genres': '["Drama", "History"]',
                    'cast': '["Umuhire Clarisse", "Hakizimana Eric"]',
                    'producer': 'Rwanda Film Studios',
                    'has_free_preview': True,
                    'is_active': True,
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = MovieCreateSerializer(data=request.data)
        if serializer.is_valid():
            movie = serializer.save()
            send_new_movie_email(movie)
            return Response(MovieDetailSerializer(movie).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MovieUpdateView(APIView):
    """
    Partially update an existing movie.
    All fields optional — send only what you want to change.
    Requires admin auth.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - Admin'],
        summary='Update a movie (partial)',
        description=(
            'Partially update a movie. Send only the fields you want to change as **multipart/form-data**. '
            'File fields replace the existing file when provided.'
        ),
        request={
            'multipart/form-data': MovieCreateSerializer,
        },
        responses={
            200: MovieDetailSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Admin access required'),
            404: OpenApiResponse(description='Movie not found'),
        },
    )
    def patch(self, request, id):
        try:
            movie = Movie.objects.get(id=id)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MovieCreateSerializer(movie, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            movie.refresh_from_db()
            return Response(MovieDetailSerializer(movie).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MovieDeleteView(APIView):
    """
    Delete a movie record.
    Note: S3 media files are NOT deleted automatically.
    Requires admin auth.
    """
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - Admin'],
        summary='Delete a movie',
        description=(
            'Permanently deletes a movie record from the database. '
            '**Note:** media files stored in S3 are not removed automatically.'
        ),
        responses={
            204: OpenApiResponse(description='Deleted successfully'),
            403: OpenApiResponse(description='Admin access required'),
            404: OpenApiResponse(description='Movie not found'),
        },
    )
    def delete(self, request, id):
        try:
            movie = Movie.objects.get(id=id)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        movie.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────
# S3 Multipart Upload — Admin only
# ─────────────────────────────────────────────

def _s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )


class InitiateMultipartUploadView(APIView):
    """Initiate an S3 multipart upload session for large video files."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - S3 Multipart Upload'],
        summary='Initiate multipart upload',
        description=(
            'Starts a new S3 multipart upload and returns an `upload_id` and `file_key`. '
            'Use these in all subsequent sign-part and complete calls. '
            'Recommended for files larger than 100 MB.'
        ),
        request=inline_serializer(
            name='InitiateUploadRequest',
            fields={
                'file_name': drf_serializers.CharField(help_text='Original filename, e.g. movie.mp4'),
                'file_type': drf_serializers.CharField(help_text='MIME type, e.g. video/mp4'),
                'field_name': drf_serializers.ChoiceField(
                    choices=['video_file', 'trailer_file', 'thumbnail', 'backdrop'],
                    help_text='Which movie field this file belongs to',
                    required=False,
                ),
            }
        ),
        responses={
            200: inline_serializer(
                name='InitiateUploadResponse',
                fields={
                    'upload_id': drf_serializers.CharField(),
                    'file_key': drf_serializers.CharField(),
                }
            ),
            400: OpenApiResponse(description='Missing file_name or file_type'),
        },
    )
    def post(self, request):
        file_name = request.data.get('file_name')
        file_type = request.data.get('file_type')

        if not file_name or not file_type:
            return Response({'error': 'Missing file_name or file_type'}, status=400)

        field_name = request.data.get('field_name')
        ext = os.path.splitext(file_name)[1]
        unique_filename = f"{uuid.uuid4()}{ext}"

        folder_map = {
            'video_file': 'movies/full',
            'trailer_file': 'movies/trailers',
            'thumbnail': 'movies/thumbnails',
            'backdrop': 'movies/backdrops',
        }
        folder = folder_map.get(field_name) or (
            'movies/full' if file_type.startswith('video/') else
            'movies/thumbnails' if file_type.startswith('image/') else
            'movies/uploads'
        )
        key = f"{folder}/{unique_filename}"

        try:
            mp_upload = _s3_client().create_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=key,
                ContentType=file_type,
            )
            return Response({'upload_id': mp_upload['UploadId'], 'file_key': key})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class SignMultipartUploadPartView(APIView):
    """Generate a pre-signed URL for uploading a single part."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - S3 Multipart Upload'],
        summary='Sign an upload part',
        description='Returns a pre-signed S3 URL for uploading one chunk. Expires in 1 hour.',
        request=inline_serializer(
            name='SignPartRequest',
            fields={
                'upload_id': drf_serializers.CharField(),
                'file_key': drf_serializers.CharField(),
                'part_number': drf_serializers.IntegerField(help_text='Part number (1-based index)'),
            }
        ),
        responses={
            200: inline_serializer(
                name='SignPartResponse',
                fields={'url': drf_serializers.URLField()}
            ),
            400: OpenApiResponse(description='Missing required fields'),
        },
    )
    def post(self, request):
        upload_id = request.data.get('upload_id')
        file_key = request.data.get('file_key')
        part_number = request.data.get('part_number')

        if not all([upload_id, file_key, part_number]):
            return Response({'error': 'Missing required fields'}, status=400)

        try:
            url = _s3_client().generate_presigned_url(
                ClientMethod='upload_part',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': file_key,
                    'UploadId': upload_id,
                    'PartNumber': int(part_number),
                },
                ExpiresIn=3600,
            )
            return Response({'url': url})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class CompleteMultipartUploadView(APIView):
    """Finalize a multipart upload after all parts have been uploaded."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - S3 Multipart Upload'],
        summary='Complete multipart upload',
        description='Assembles all uploaded parts into the final S3 object. Call this after every part is uploaded.',
        request=inline_serializer(
            name='CompleteUploadRequest',
            fields={
                'upload_id': drf_serializers.CharField(),
                'file_key': drf_serializers.CharField(),
                'parts': drf_serializers.ListField(
                    child=inline_serializer(
                        name='UploadPart',
                        fields={
                            'ETag': drf_serializers.CharField(),
                            'PartNumber': drf_serializers.IntegerField(),
                        }
                    ),
                    help_text='List of {ETag, PartNumber} pairs returned by S3 during each part upload',
                ),
            }
        ),
        responses={
            200: inline_serializer(
                name='CompleteUploadResponse',
                fields={'status': drf_serializers.CharField()}
            ),
            400: OpenApiResponse(description='Missing required fields'),
        },
    )
    def post(self, request):
        upload_id = request.data.get('upload_id')
        file_key = request.data.get('file_key')
        parts = request.data.get('parts')

        if not all([upload_id, file_key, parts]):
            return Response({'error': 'Missing required fields'}, status=400)

        try:
            _s3_client().complete_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=file_key,
                UploadId=upload_id,
                MultipartUpload={'Parts': parts},
            )
        except Exception as e:
            return Response({'error': str(e)}, status=500)

        hls_triggered = False
        movie_id = request.data.get('movie_id')
        field_name = request.data.get('field_name')
        if movie_id and field_name == 'video_file':
            try:
                from .transcoding import start_hls_transcode
                start_hls_transcode(int(movie_id))
                hls_triggered = True
            except Exception:
                pass  # Never fail the upload response due to transcode kick-off errors

        return Response({'status': 'complete', 'hls_triggered': hls_triggered})


class AbortMultipartUploadView(APIView):
    """Cancel an in-progress multipart upload and free S3 storage."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminRole]

    @extend_schema(
        tags=['Movies - S3 Multipart Upload'],
        summary='Abort multipart upload',
        description='Cancels the multipart upload and releases any partially uploaded data from S3.',
        request=inline_serializer(
            name='AbortUploadRequest',
            fields={
                'upload_id': drf_serializers.CharField(),
                'file_key': drf_serializers.CharField(),
            }
        ),
        responses={
            200: inline_serializer(
                name='AbortUploadResponse',
                fields={'status': drf_serializers.CharField()}
            ),
            400: OpenApiResponse(description='Missing required fields'),
        },
    )
    def post(self, request):
        upload_id = request.data.get('upload_id')
        file_key = request.data.get('file_key')

        if not all([upload_id, file_key]):
            return Response({'error': 'Missing required fields'}, status=400)

        try:
            _s3_client().abort_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=file_key,
                UploadId=upload_id,
            )
            return Response({'status': 'aborted'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


# ─────────────────────────────────────────────
# My List  (purchased movies + continue-watching)
# ─────────────────────────────────────────────

class MyListView(APIView):
    """
    Returns all movies the authenticated user has purchased.
    Each movie card includes watch-progress fields so the frontend can render
    the "Continue Watching" progress bar inline.

    GET /api/movies/my-list/
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Movies - Viewer'],
        summary='My List — purchased movies with watch progress',
        description=(
            'Returns every movie the user has paid for, enriched with their '
            'current playback position.  Use `completed=false` entries to '
            'build a "Continue Watching" row.'
        ),
        responses={200: MyListMovieSerializer(many=True)},
    )
    def get(self, request):
        # Fetch movie IDs the user has paid for.
        paid_movie_ids = Payment.objects.filter(
            user=request.user, status='Completed'
        ).values_list('movie_id', flat=True)

        movies = Movie.objects.filter(id__in=paid_movie_ids, is_active=True)

        # Fetch all progress records for this user in one query.
        progress_map = {
            wp.movie_id: wp
            for wp in WatchProgress.objects.filter(
                user=request.user, movie_id__in=paid_movie_ids
            )
        }

        # Annotate each movie with its progress object so the serializer can
        # access it without triggering additional queries.
        for movie in movies:
            movie.watch_progress_obj = progress_map.get(movie.id)

        serializer = MyListMovieSerializer(movies, many=True)
        return Response(serializer.data)


class ContinueWatchingView(APIView):
    """
    Returns movies the user has started watching but not yet completed,
    ordered by most recently watched.

    GET /api/movies/continue-watching/
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Movies - Viewer'],
        summary='Continue Watching — in-progress movies',
        description='Returns movies where the user has saved progress but has not yet finished watching.',
        responses={200: MyListMovieSerializer(many=True)},
    )
    def get(self, request):
        progress_qs = WatchProgress.objects.filter(
            user=request.user,
            completed=False,
            progress_seconds__gt=0,
        ).select_related('movie').order_by('-last_watched_at')

        movies = []
        for wp in progress_qs:
            if wp.movie and wp.movie.is_active:
                wp.movie.watch_progress_obj = wp
                movies.append(wp.movie)

        serializer = MyListMovieSerializer(movies, many=True)
        return Response(serializer.data)


# ─────────────────────────────────────────────
# Watch Progress
# ─────────────────────────────────────────────

class WatchProgressView(APIView):
    """
    GET  /api/movies/<id>/progress/ — retrieve the user's saved position.
    POST /api/movies/<id>/progress/ — save (upsert) the playback position.

    The frontend should call POST periodically during playback (e.g. every 15 s)
    and on pause/close so the server always has an up-to-date resume point.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Movies - Viewer'],
        summary='Get watch progress for a movie',
        responses={
            200: WatchProgressSerializer(),
            404: OpenApiResponse(description='No progress saved yet'),
        },
    )
    def get(self, request, id):
        try:
            wp = WatchProgress.objects.get(user=request.user, movie_id=id)
        except WatchProgress.DoesNotExist:
            return Response({'progress_seconds': 0, 'duration_seconds': 0, 'completed': False})
        serializer = WatchProgressSerializer(wp)
        return Response(serializer.data)

    @extend_schema(
        tags=['Movies - Viewer'],
        summary='Save watch progress for a movie',
        request=WatchProgressSerializer,
        responses={
            200: WatchProgressSerializer(),
            403: OpenApiResponse(description='User has not purchased this movie'),
        },
    )
    def post(self, request, id):
        # Only users who have purchased the movie can save progress.
        has_access = Payment.objects.filter(
            user=request.user, movie_id=id, status='Completed'
        ).exists()
        if not has_access:
            return Response(
                {'error': 'You have not purchased this movie.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            movie = Movie.objects.get(pk=id)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Run all input validation through the serializer to prevent type errors
        # from raw string values reaching numeric comparisons.
        # Inject the movie id so the serializer's cross-field validator can run.
        input_serializer = WatchProgressSerializer(
            data={**request.data, 'movie': id}
        )
        input_serializer.is_valid(raise_exception=True)
        progress_seconds = input_serializer.validated_data.get('progress_seconds', 0)
        duration_seconds = input_serializer.validated_data.get('duration_seconds', 0)

        # Mark as completed when the viewer reaches ≥ 90% of the total duration.
        # Server-side computation — the client cannot force completion.
        completed = (
            duration_seconds > 0
            and progress_seconds >= duration_seconds * 0.9
        )

        wp, _ = WatchProgress.objects.update_or_create(
            user=request.user,
            movie=movie,
            defaults={
                'progress_seconds': progress_seconds,
                'duration_seconds': duration_seconds,
                'completed': completed,
            },
        )
        serializer = WatchProgressSerializer(wp)
        return Response(serializer.data)

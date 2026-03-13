from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from .models import Movie
from .serializers import (
    MovieSerializer, 
    MovieDetailSerializer,
    MovieVideoAccessSerializer,
    MovieCreateSerializer
)
from rest_framework.permissions import IsAdminUser
from django.conf import settings
import boto3
import uuid
import os
from rest_framework.authentication import SessionAuthentication
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes


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
        page = int(request.GET.get('page', 1))
        sort_by = request.GET.get('sort_by', 'popularity.desc')
        
        movies = Movie.objects.filter(is_active=True)
        
        if sort_by == 'popularity.desc':
            movies = movies.order_by('-views')
        elif sort_by == 'release_date.desc':
            movies = movies.order_by('-release_date')
        elif sort_by == 'rating.desc':
            movies = movies.order_by('-rating')
        else:
            movies = movies.order_by('-views')
        
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        
        total_results = movies.count()
        movies_page = movies[start:end]
        
        serializer = MovieSerializer(movies_page, many=True)
        
        return Response({
            'page': page,
            'results': serializer.data,
            'total_results': total_results,
            'total_pages': (total_results + page_size - 1) // page_size
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
        page = int(request.GET.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        
        movies = Movie.objects.filter(is_active=True).order_by('-views')
        total_results = movies.count()
        movies_page = movies[start:end]
        
        serializer = MovieSerializer(movies_page, many=True)
        
        return Response({
            'page': page,
            'results': serializer.data,
            'total_results': total_results,
            'total_pages': (total_results + page_size - 1) // page_size
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
        page = int(request.GET.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        
        movies = Movie.objects.filter(is_active=True).order_by('-created_at')
        total_results = movies.count()
        movies_page = movies[start:end]
        
        serializer = MovieSerializer(movies_page, many=True)
        
        return Response({
            'page': page,
            'results': serializer.data,
            'total_results': total_results,
            'total_pages': (total_results + page_size - 1) // page_size
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
        page = int(request.GET.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        
        movies = Movie.objects.filter(is_active=True, rating__gte=4.0).order_by('-rating')
        total_results = movies.count()
        movies_page = movies[start:end]
        
        serializer = MovieSerializer(movies_page, many=True)
        
        return Response({
            'page': page,
            'results': serializer.data,
            'total_results': total_results,
            'total_pages': (total_results + page_size - 1) // page_size
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
        page = int(request.GET.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        
        today = timezone.now().date()
        movies = Movie.objects.filter(
            is_active=True,
            release_date__gte=today
        ).order_by('release_date')
        
        total_results = movies.count()
        movies_page = movies[start:end]
        
        serializer = MovieSerializer(movies_page, many=True)
        
        return Response({
            'page': page,
            'results': serializer.data,
            'total_results': total_results,
            'total_pages': (total_results + page_size - 1) // page_size
        })


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
            serializer = MovieDetailSerializer(movie)
            return Response(serializer.data)
        except Movie.DoesNotExist:
            return Response(
                {'error': 'Movie not found'},
                status=status.HTTP_404_NOT_FOUND
            )


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

            videos = []

            # Add trailer if available
            if movie.trailer_file:
                videos.append({
                    'url': movie.trailer_url,   # CloudFront/S3 URL
                    'name': f'{movie.title} - Trailer',
                    'type': 'Trailer',
                    'site': 'Local',
                    'duration_seconds': movie.trailer_duration_seconds,
                    'is_free': True
                })

            # Add full video info
            if movie.video_file:
                videos.append({
                    'url': movie.video_url,     # CloudFront/S3 URL
                    'name': f'{movie.title} - Full Movie',
                    'type': 'Full Movie',
                    'site': 'Local',
                    'duration_minutes': movie.duration_minutes,
                    'requires_payment': True,
                    'price': movie.price
                })

            return Response({
                'id': movie.id,
                'results': videos
            })
        except Movie.DoesNotExist:
            return Response(
                {'error': 'Movie not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class MovieStreamView(APIView):
    """
    Get streaming URL for full movie.
    In development: Always grants access.
    In production: Verify payment before granting access.
    """
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)

            # TODO: In production, check payment status
            # if not self.has_user_paid(request.user, movie):
            #     return Response(
            #         {'error': 'Payment required', 'price': movie.price},
            #         status=status.HTTP_402_PAYMENT_REQUIRED
            #     )

            # Increment view count
            movie.increment_views()

            serializer = MovieVideoAccessSerializer(
                movie,
                context={'request': request}
            )

            return Response({
                'movie': serializer.data,
                'stream_url': movie.video_url,  # CloudFront/S3 absolute URL
                'message': 'Development mode - payment not required'
            })

        except Movie.DoesNotExist:
            return Response(
                {'error': 'Movie not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class MovieTrailerView(APIView):
    """
    Get trailer streaming URL - always free.
    """
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)

            if not movie.trailer_file:
                return Response(
                    {'error': 'Trailer not available for this movie'},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                'id': movie.id,
                'title': movie.title,
                'stream_url': movie.trailer_url,  # CloudFront/S3 absolute URL
                'duration_seconds': movie.trailer_duration_seconds,
                'is_free': True
            })

        except Movie.DoesNotExist:
            return Response(
                {'error': 'Movie not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class MovieImagesView(APIView):
    """Get image information for a movie"""
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
            return Response({
                'id': movie.id,
                'backdrops': [
                    {
                        'file_path': movie.backdrop_url,
                        'width': 1280,
                        'height': 720
                    }
                ] if movie.backdrop_url else [],
                'posters': [
                    {
                        'file_path': movie.thumbnail_url,
                        'width': 300,
                        'height': 450
                    }
                ]
            })
        except Movie.DoesNotExist:
            return Response(
                {'error': 'Movie not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class MovieCreateView(APIView):
    """
    Create a new movie
    Accepts multipart/form-data for file uploads
    """
    # parser_classes = (MultiPartParser, FormParser) # APIView doesn't have default parsers for everything, but usually REST_FRAMEWORK defaults include them. 
    # Better to interpret explicit parsers if we want to be safe, but let's stick to standard APIView for now or use CreateAPIView which is better.
    
    def post(self, request):
        serializer = MovieCreateSerializer(data=request.data)
        if serializer.is_valid():
            movie = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InitiateMultipartUploadView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request):
        file_name = request.data.get('file_name')
        file_type = request.data.get('file_type')
        
        if not file_name or not file_type:
            return Response({'error': 'Missing file_name or file_type'}, status=400)

        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )

        field_name = request.data.get('field_name')

        # Generate unique file path
        ext = os.path.splitext(file_name)[1]
        unique_filename = f"{uuid.uuid4()}{ext}"
        
        # Determine folder based on field name or file type
        key = f"movies/uploads/{unique_filename}"
        
        if field_name == 'video_file':
            key = f"movies/full/{unique_filename}"
        elif field_name == 'trailer_file':
            key = f"movies/trailers/{unique_filename}"
        elif field_name == 'thumbnail':
            key = f"movies/thumbnails/{unique_filename}"
        elif field_name == 'backdrop':
            key = f"movies/backdrops/{unique_filename}"
        elif file_type.startswith('video/'):
             key = f"movies/full/{unique_filename}"
        elif file_type.startswith('image/'):
             key = f"movies/thumbnails/{unique_filename}"

        try:
            mp_upload = s3_client.create_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=key,
                ContentType=file_type
            )
            
            return Response({
                'upload_id': mp_upload['UploadId'],
                'file_key': key
            })
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class SignMultipartUploadPartView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request):
        data = request.data
        upload_id = data.get('upload_id')
        file_key = data.get('file_key')
        part_number = data.get('part_number')

        if not all([upload_id, file_key, part_number]):
            return Response({'error': 'Missing required fields'}, status=400)

        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )

        try:
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod='upload_part',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': file_key,
                    'UploadId': upload_id,
                    'PartNumber': int(part_number)
                },
                ExpiresIn=3600
            )
            
            return Response({'url': presigned_url})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class CompleteMultipartUploadView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request):
        data = request.data
        upload_id = data.get('upload_id')
        file_key = data.get('file_key')
        parts = data.get('parts') # List of {'ETag': '...', 'PartNumber': 1}

        if not all([upload_id, file_key, parts]):
            return Response({'error': 'Missing required fields'}, status=400)

        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )

        try:
            s3_client.complete_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=file_key,
                UploadId=upload_id,
                MultipartUpload={'Parts': parts}
            )
            return Response({'status': 'complete'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class AbortMultipartUploadView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request):
        data = request.data
        upload_id = data.get('upload_id')
        file_key = data.get('file_key')

        if not all([upload_id, file_key]):
            return Response({'error': 'Missing required fields'}, status=400)

        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )

        try:
            s3_client.abort_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=file_key,
                UploadId=upload_id
            )
            return Response({'status': 'aborted'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from .models import Movie
from .serializers import (
    MovieSerializer, 
    MovieDetailSerializer,
    MovieVideoAccessSerializer
)


class DiscoverMoviesView(APIView):
    """General movie discovery endpoint"""
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
    Get video information for a movie
    Returns trailer (always accessible) and full video info
    """
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
            
            videos = []
            
            # Add trailer if available
            if movie.trailer_key:
                videos.append({
                    'key': movie.trailer_key,
                    'name': f'{movie.title} - Trailer',
                    'type': 'Trailer',
                    'site': 'Local',
                    'duration_seconds': movie.trailer_duration_seconds,
                    'is_free': True
                })
            
            # Add full video info
            videos.append({
                'key': movie.video_key,
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
    Get streaming URL for full movie
    In development: Always grants access
    In production: Verify payment before granting access
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
                'stream_url': f'/media/{movie.video_key}',  # Adjust based on your storage
                'message': 'Development mode - payment not required'
            })
            
        except Movie.DoesNotExist:
            return Response(
                {'error': 'Movie not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class MovieTrailerView(APIView):
    """
    Get trailer streaming URL - always free
    """
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, is_active=True)
            
            if not movie.trailer_key:
                return Response(
                    {'error': 'Trailer not available for this movie'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            return Response({
                'id': movie.id,
                'title': movie.title,
                'trailer_key': movie.trailer_key,
                'stream_url': f'/media/{movie.trailer_key}',
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

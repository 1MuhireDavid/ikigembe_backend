from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from apps.users.permissions import IsProducerRole
from apps.movies.models import Movie
from apps.movies.serializers import ProducerMovieListSerializer


class ProducerBaseView(APIView):
    permission_classes = [IsAuthenticated, IsProducerRole]


class ProducerMyMoviesView(ProducerBaseView):
    @extend_schema(
        tags=["Producer Dashboard"],
        summary="List my movies",
        description=(
            "Returns all movies belonging to the authenticated producer, ordered by most recently added. "
            "Read-only — uploading, editing, and deleting movies is handled by the Admin."
        ),
    )
    def get(self, request):
        movies = Movie.objects.filter(
            producer_profile=request.user
        ).order_by('-created_at')

        page = int(request.GET.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        total = movies.count()

        return Response({
            'page': page,
            'results': ProducerMovieListSerializer(movies[start:start + page_size], many=True).data,
            'total_results': total,
            'total_pages': (total + page_size - 1) // page_size,
        })

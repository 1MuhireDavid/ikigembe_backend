from django.core.management.base import BaseCommand
from apps.movies.models import Movie
from django.utils import timezone
import random
from datetime import date, timedelta
from django.db import models

class Command(BaseCommand):
    help = "Seed database with sample Rwandan-themed movies including trailers"

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("Clearing existing movies..."))
        Movie.objects.all().delete()

        # Rwandan film themes and titles
        sample_movies = [
            {
                "title": "Umurinzi w'Imana",
                "overview": "A powerful story of resilience and hope during Rwanda's darkest hours, following a family's journey through tragedy and healing.",
                "thumbnail_url": "https://picsum.photos/300/450?random=1",
                "backdrop_url": "https://picsum.photos/1280/720?random=1",
                "duration": 18  # minutes
            },
            {
                "title": "The Kigali Streets",
                "overview": "A young entrepreneur navigates the bustling streets of Kigali, building a tech startup while honoring traditional values.",
                "thumbnail_url": "https://picsum.photos/300/450?random=2",
                "backdrop_url": "https://picsum.photos/1280/720?random=2",
                "duration": 15
            },
            {
                "title": "Beyond the Hills",
                "overview": "Two childhood friends reunite after years apart, discovering their paths have taken them to opposite sides of Rwanda's transformation.",
                "thumbnail_url": "https://picsum.photos/300/450?random=3",
                "backdrop_url": "https://picsum.photos/1280/720?random=3",
                "duration": 20
            },
            {
                "title": "Amakuru y'Ubuntu",
                "overview": "A documentary-style drama exploring the meaning of Ubuntu in modern Rwanda through interconnected stories of kindness.",
                "thumbnail_url": "https://picsum.photos/300/450?random=4",
                "backdrop_url": "https://picsum.photos/1280/720?random=4",
                "duration": 12
            },
            {
                "title": "Digital Dreams",
                "overview": "Young developers at a Kigali tech hub race to build an app that could revolutionize African e-commerce.",
                "thumbnail_url": "https://picsum.photos/300/450?random=5",
                "backdrop_url": "https://picsum.photos/1280/720?random=5",
                "duration": 17
            },
            {
                "title": "The Coffee Trail",
                "overview": "Following Rwandan coffee from the hills of Nyamasheke to prestigious cafés around the world.",
                "thumbnail_url": "https://picsum.photos/300/450?random=6",
                "backdrop_url": "https://picsum.photos/1280/720?random=6",
                "duration": 14
            },
            {
                "title": "Inganzo Nshya",
                "overview": "A traditional drummer teaches a new generation while adapting ancient rhythms to modern music.",
                "thumbnail_url": "https://picsum.photos/300/450?random=7",
                "backdrop_url": "https://picsum.photos/1280/720?random=7",
                "duration": 16
            },
            {
                "title": "The Market Day",
                "overview": "A day in the life of Kimironko market, where diverse lives intersect and stories unfold.",
                "thumbnail_url": "https://picsum.photos/300/450?random=8",
                "backdrop_url": "https://picsum.photos/1280/720?random=8",
                "duration": 13
            },
            {
                "title": "Sunrise Over Volcanoes",
                "overview": "A park ranger's dedication to protecting mountain gorillas while supporting his family and community.",
                "thumbnail_url": "https://picsum.photos/300/450?random=9",
                "backdrop_url": "https://picsum.photos/1280/720?random=9",
                "duration": 19
            },
            {
                "title": "The Last Bus",
                "overview": "Strangers on a bus journey from Kigali to Rubavu share stories that change their perspectives on life.",
                "thumbnail_url": "https://picsum.photos/300/450?random=10",
                "backdrop_url": "https://picsum.photos/1280/720?random=10",
                "duration": 11
            },
            {
                "title": "Umuganda Spirit",
                "overview": "A community comes together during monthly Umuganda to build more than just infrastructure.",
                "thumbnail_url": "https://picsum.photos/300/450?random=11",
                "backdrop_url": "https://picsum.photos/1280/720?random=11",
                "duration": 10
            },
            {
                "title": "Fashion Forward",
                "overview": "Young designers blend traditional Rwandan patterns with contemporary fashion, aiming for international runways.",
                "thumbnail_url": "https://picsum.photos/300/450?random=12",
                "backdrop_url": "https://picsum.photos/1280/720?random=12",
                "duration": 15
            },
        ]

        today = timezone.now().date()
        created_count = 0

        # Create mix of past, current, and upcoming films
        for i, movie_data in enumerate(sample_movies):
            # Vary release dates
            if i < 6:
                # Past releases (already released)
                days_ago = random.randint(30, 365)
                release_date = today - timedelta(days=days_ago)
            elif i < 9:
                # Recent releases (this month)
                days_ago = random.randint(1, 15)
                release_date = today - timedelta(days=days_ago)
            else:
                # Upcoming releases
                days_ahead = random.randint(7, 90)
                release_date = today + timedelta(days=days_ahead)

            # Generate video keys
            title_slug = movie_data['title'].lower().replace(' ', '_').replace("'", '')
            
            Movie.objects.create(
                title=movie_data['title'],
                overview=movie_data['overview'],
                thumbnail_url=movie_data['thumbnail_url'],
                backdrop_url=movie_data['backdrop_url'],
                
                # Video files
                video_key=f"movies/full/{title_slug}.mp4",
                trailer_key=f"movies/trailers/{title_slug}_trailer.mp4",
                
                # Duration
                duration_minutes=movie_data['duration'],
                trailer_duration_seconds=random.choice([90, 120, 150]),  # 1.5-2.5 min trailers
                
                # Pricing
                price=500,  # 500 RWF as per project proposal
                
                # Metrics
                views=random.randint(50, 2500) if release_date <= today else 0,
                rating=round(random.uniform(3.5, 5.0), 1) if release_date <= today else 0.0,
                
                # Status
                release_date=release_date,
                is_active=True,
                has_free_preview=True,  # All movies have free trailers
            )
            created_count += 1

        # Create additional variations for a fuller catalog
        for i in range(15):
            base = random.choice(sample_movies)
            days_variance = random.randint(-180, 60)
            release_date = today + timedelta(days=days_variance)
            
            title = f"{base['title']} - Episode {i+1}"
            title_slug = title.lower().replace(' ', '_').replace("'", '')
            
            Movie.objects.create(
                title=title,
                overview=f"{base['overview']} (Part {i+1})",
                thumbnail_url=f"https://picsum.photos/300/450?random={13+i}",
                backdrop_url=f"https://picsum.photos/1280/720?random={13+i}",
                
                # Video files
                video_key=f"movies/full/episode_{i+1}.mp4",
                trailer_key=f"movies/trailers/episode_{i+1}_trailer.mp4",
                
                # Duration
                duration_minutes=random.randint(10, 20),
                trailer_duration_seconds=random.choice([90, 120, 150]),
                
                # Pricing
                price=500,
                
                # Metrics
                views=random.randint(0, 3000) if release_date <= today else 0,
                rating=round(random.uniform(3.0, 5.0), 1) if release_date <= today else 0.0,
                
                # Status
                release_date=release_date,
                is_active=True,
                has_free_preview=True,
            )
            created_count += 1

        # Calculate statistics
        from django.db.models import Avg
        total_movies = Movie.objects.count()
        past_movies = Movie.objects.filter(release_date__lt=today).count()
        upcoming_movies = Movie.objects.filter(release_date__gte=today).count()
        avg_rating = Movie.objects.filter(rating__gt=0).aggregate(avg=Avg('rating'))['avg'] or 0
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Successfully seeded {created_count} movies!\n\n"
                f"📊 Statistics:\n"
                f"   - Total movies: {total_movies}\n"
                f"   - Past releases: {past_movies}\n"
                f"   - Upcoming: {upcoming_movies}\n"
                f"   - Average rating: {avg_rating:.1f}/5.0\n\n"
                f"🎬 Video Access:\n"
                f"   - All movies have trailers (FREE)\n"
                f"   - Full movies available (payment required in production)\n"
                f"   - Development mode: All content accessible\n"
            )
        )
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model

from apps.movies.models import Movie
from apps.payments.models import Payment, WithdrawalRequest

User = get_user_model()


def create_user(email, phone, first_name, last_name, role, password, **extra_fields):
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "phone_number": phone,
            "first_name": first_name,
            "last_name": last_name,
            "role": role,
            **extra_fields
        }
    )

    if created:
        user.set_password(password)
        user.save()

    return user


def create_test_data():
    now = timezone.now()

    print("Creating users...")

    admin = create_user(
        email="admin@test.com",
        phone="0780000000",
        first_name="Test",
        last_name="Admin",
        role=User.Role.ADMIN,
        password="password123",
        is_staff=True,
        is_superuser=True,
    )

    producer = create_user(
        email="producer@test.com",
        phone="0780000001",
        first_name="Test",
        last_name="Producer",
        role=User.Role.PRODUCER,
        password="password123",
    )

    viewer = create_user(
        email="viewer@test.com",
        phone="0780000002",
        first_name="Test",
        last_name="Viewer",
        role=User.Role.VIEWER,
        password="password123",
    )

    print("Creating movie...")

    movie, _ = Movie.objects.get_or_create(
        title="Test Movie",
        defaults={
            "overview": "Test movie for dashboard validation",
            "producer": producer.full_name,  # ✅ property is OK here (not DB field)
            "producer_profile": producer,
            "price": 1000,
            "duration_minutes": 120,
            "release_date": now.date(),
            "is_active": True,
        },
    )

    print("Creating payments...")

    # Payment today
    p1, created = Payment.objects.get_or_create(
        user=viewer,
        movie=movie,
        amount=1000,
        status="Completed",
    )

    if created:
        p1.created_at = now
        p1.save()

    # Payment 5 days ago (avoid duplicates)
    p2, created = Payment.objects.get_or_create(
        user=viewer,
        movie=movie,
        amount=1000,
        status="Completed",
        created_at=now - timedelta(days=5),  # won't work directly
    )

    if created:
        Payment.objects.filter(id=p2.id).update(
            created_at=now - timedelta(days=5)
        )

    print("Creating withdrawals...")

    w1, _ = WithdrawalRequest.objects.get_or_create(
        producer=producer,
        amount=700,
        status="Approved",
    )

    if not w1.processed_at:
        w1.created_at = now - timedelta(days=2)
        w1.processed_at = now - timedelta(days=1)
        w1.save()

    w2, _ = WithdrawalRequest.objects.get_or_create(
        producer=producer,
        amount=500,
        status="Pending",
    )

    print("\n--- Test Data Setup Complete ---")
    print(f"Admin: {admin.email} / password123")
    print(f"Producer: {producer.email} / password123")
    print(f"Viewer: {viewer.email} / password123")
    print(f"Movie: {movie.title}")
    print("Payments: 2 completed")
    print("Withdrawals: 1 Approved, 1 Pending")


class Command(BaseCommand):
    help = "Seed test data"

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding test data...\n")
        create_test_data()
        self.stdout.write(self.style.SUCCESS("✅ Done seeding test data!"))
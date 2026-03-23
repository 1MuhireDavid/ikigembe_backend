from django.db import models
from django.conf import settings

User = settings.AUTH_USER_MODEL

class Payment(models.Model):
    """
    Model representing a user paying to watch a movie.
    """
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Failed', 'Failed'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    movie = models.ForeignKey('movies.Movie', on_delete=models.SET_NULL, null=True, related_name='payments')
    amount = models.PositiveIntegerField(help_text="Amount in RWF")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Completed')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        movie_title = self.movie.title if self.movie else "Unknown Movie"
        return f"{self.user} - {movie_title} - {self.amount} RWF"

class WithdrawalRequest(models.Model):
    """
    Model representing a producer requesting to withdraw earnings.
    """
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    )
    producer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawal_requests', limit_choices_to={'role': 'Producer'})
    amount = models.PositiveIntegerField(help_text="Amount to withdraw in RWF")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Withdrawal - {self.producer} - {self.amount} RWF ({self.status})"

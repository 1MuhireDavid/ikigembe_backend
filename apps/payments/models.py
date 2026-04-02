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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    deposit_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="PawaPay deposit ID")
    phone_number = models.CharField(max_length=20, null=True, blank=True, help_text="Payer's phone number")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        movie_title = self.movie.title if self.movie else "Unknown Movie"
        return f"{self.user} - {movie_title} - {self.amount} RWF"

class WithdrawalRequest(models.Model):
    """
    Model representing a producer requesting to withdraw earnings.
    Workflow: Pending → Approved (Admin) → Completed (Finance).
    Once Completed, the record is immutable (enforced in views).
    """
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Processing', 'Processing'),
        ('Rejected', 'Rejected'),
        ('Completed', 'Completed'),
        ('Failed', 'Failed'),
    )
    PAYMENT_METHOD_CHOICES = (
        ('Bank', 'Bank'),
        ('MoMo', 'MoMo'),
    )
    MOMO_PROVIDER_CHOICES = (
        ('MTN', 'MTN'),
        ('Airtel', 'Airtel'),
    )

    producer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawal_requests', limit_choices_to={'role': 'Producer'})
    amount = models.PositiveIntegerField(help_text="Amount to withdraw in RWF")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    payout_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="PawaPay payout ID (MoMo withdrawals only)")
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    # Payout destination
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    account_holder_name = models.CharField(max_length=150, blank=True, null=True)
    momo_number = models.CharField(max_length=20, blank=True, null=True)
    momo_provider = models.CharField(max_length=10, choices=MOMO_PROVIDER_CHOICES, blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Withdrawal - {self.producer} - {self.amount} RWF ({self.status})"

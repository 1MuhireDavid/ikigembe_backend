from django.contrib import admin
from .models import Payment, WithdrawalRequest

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'movie', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')

@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ('producer', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')

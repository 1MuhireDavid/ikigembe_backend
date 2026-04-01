from rest_framework import serializers
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.payments.models import Payment, WithdrawalRequest


def get_producer_wallet(producer):
    """
    Compute wallet stats for a producer.

    total_earnings  = 70% of all completed movie-payment revenue
    wallet_balance  = total_earnings minus all non-rejected withdrawal amounts
                      (Pending amounts are locked to prevent double-spending;
                       Rejected amounts are automatically freed)
    """
    raw_revenue = Payment.objects.filter(
        movie__producer_profile=producer,
        status='Completed',
    ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

    total_earnings = (raw_revenue * 70) // 100

    locked = WithdrawalRequest.objects.filter(
        producer=producer,
        status__in=['Pending', 'Approved', 'Processing', 'Completed'],
    ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

    pending = WithdrawalRequest.objects.filter(
        producer=producer,
        status='Pending',
    ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

    total_withdrawn = WithdrawalRequest.objects.filter(
        producer=producer,
        status='Completed',
    ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

    return {
        'total_earnings': total_earnings,
        'wallet_balance': total_earnings - locked,
        'pending_withdrawals': pending,
        'total_withdrawn': total_withdrawn,
    }


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    """Producer-facing serializer: create requests and view history."""

    class Meta:
        model = WithdrawalRequest
        fields = [
            'id', 'amount', 'payment_method',
            'bank_name', 'account_number', 'account_holder_name',
            'momo_number', 'momo_provider',
            'status', 'created_at', 'processed_at',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'processed_at']

    def validate(self, data):
        method = data.get('payment_method')
        if not method:
            raise serializers.ValidationError({'payment_method': 'This field is required.'})
        if method == 'Bank':
            for field in ['bank_name', 'account_number', 'account_holder_name']:
                if not data.get(field):
                    raise serializers.ValidationError({field: 'Required for Bank payout.'})
        if method == 'MoMo':
            for field in ['momo_number', 'momo_provider']:
                if not data.get(field):
                    raise serializers.ValidationError({field: 'Required for MoMo payout.'})
        return data


class AdminWithdrawalRequestSerializer(serializers.ModelSerializer):
    """Admin-facing serializer: read-only view with producer identity and full destination details."""

    producer_name = serializers.CharField(source='producer.full_name', read_only=True)
    producer_email = serializers.CharField(source='producer.email', read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            'id', 'producer_name', 'producer_email', 'amount', 'status',
            'payment_method', 'bank_name', 'account_number', 'account_holder_name',
            'momo_number', 'momo_provider', 'created_at', 'processed_at',
        ]

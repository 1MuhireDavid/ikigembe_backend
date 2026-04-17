from rest_framework import serializers
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.payments.models import Payment, WithdrawalRequest


def producer_split(gross: int) -> tuple:
    """Return (producer_earnings, platform_commission) for a gross amount.

    Producer share is computed first as (gross * 70) // 100; commission is
    the remainder.  This guarantees producer_earnings + commission == gross
    regardless of rounding, so all endpoints report consistent figures.
    """
    producer_earnings = (gross * 70) // 100
    return producer_earnings, gross - producer_earnings


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

    total_earnings, platform_commission = producer_split(raw_revenue)

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
        'gross_revenue': raw_revenue,
        'platform_commission': platform_commission,
        'total_earnings': total_earnings,
        'wallet_balance': total_earnings - locked,
        'pending_withdrawals': pending,
        'total_withdrawn': total_withdrawn,
    }


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    """Producer-facing serializer: create requests and view history."""

    # Tax breakdown fields (30% government tax on withdrawal)
    tax_amount = serializers.SerializerMethodField(
        help_text='30% government tax deducted from the requested amount (RWF)'
    )
    amount_after_tax = serializers.SerializerMethodField(
        help_text='Final amount the producer receives after 30% tax deduction (RWF)'
    )

    class Meta:
        model = WithdrawalRequest
        fields = [
            'id', 'amount', 'tax_amount', 'amount_after_tax', 'payment_method',
            'bank_name', 'account_number', 'account_holder_name',
            'momo_number', 'momo_provider',
            'status', 'created_at', 'processed_at',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'processed_at',
                            'tax_amount', 'amount_after_tax']

    def get_tax_amount(self, obj):
        _, commission = producer_split(obj.amount)  # reuse canonical split; tax mirrors Ikigembe's 30%
        return commission

    def get_amount_after_tax(self, obj):
        after_tax, _ = producer_split(obj.amount)
        return after_tax

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

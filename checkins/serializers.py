from rest_framework import serializers

from users.serializers import PublicUserSerializer
from .models import CheckIn


class CheckInSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheckIn
        fields = [
            'id',
            'event',
            'latitude',
            'longitude',
            'is_valid',
            'checked_in_at',
        ]
        read_only_fields = ['event', 'is_valid', 'checked_in_at']


class CheckInDetailSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)

    class Meta:
        model = CheckIn
        fields = [
            'id',
            'event',
            'user',
            'latitude',
            'longitude',
            'is_valid',
            'checked_in_at',
        ]
        read_only_fields = fields

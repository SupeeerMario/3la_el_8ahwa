from rest_framework import serializers

from core import storage
from users.serializers import PublicUserSerializer
from .models import CheckIn


class CheckInSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = CheckIn
        fields = [
            'id',
            'event',
            'latitude',
            'longitude',
            'is_valid',
            'image_url',
            'checked_in_at',
        ]
        read_only_fields = ['event', 'is_valid', 'image_url', 'checked_in_at']

    def get_image_url(self, obj):
        return storage.checkin_image_url(obj)


class CheckInDetailSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = CheckIn
        fields = [
            'id',
            'event',
            'user',
            'latitude',
            'longitude',
            'is_valid',
            'image_url',
            'checked_in_at',
        ]
        read_only_fields = fields

    def get_image_url(self, obj):
        return storage.checkin_image_url(obj)

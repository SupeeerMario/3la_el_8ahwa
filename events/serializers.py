from rest_framework import serializers
from .models import Event


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            'title',
            'text',
            'latitude',
            'longitude',
            'radius_meters',
            'start_time',
            'end_time',
            'created_at'
        ]
    read_only_field = ['created_at']


    def validate_latitude(self, value):
        return round(value, 4)
    

    def validate_longitude(self, value):
        return round(value, 4)

class EventDetailSerializer(serializers.ModelSerializer):

    created_by = serializers.StringRelatedField()
    group = serializers.StringRelatedField()
    class Meta:
        model = Event
        fields = [
            'id',
            'title',
            'text',
            'latitude',
            'longitude',
            'radius_meters',
            'start_time',
            'end_time',
            'created_at',
            'created_by',
            'group'
        ]
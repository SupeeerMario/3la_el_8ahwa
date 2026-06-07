from rest_framework import serializers
from .models import Event
from django.utils import timezone


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
            'created_at',
            'active',
            'finished'
        ]
    read_only_fields = ['created_at', 'active','finished' ]


    def validate_latitude(self, value):
        return round(value, 4)
    

    def validate_longitude(self, value):
        return round(value, 4)
    
    def validate_start_time(self, value):
        if value < timezone.now():
            raise serializers.ValidationError('Start time cannot be in the past')
        return value

    def validate_end_time(self,value):
        if value < timezone.now():
            raise serializers.ValidationError('End time cannot be in the past')
        return value
        
    def validate(self, data):
        start_time = data.get('start_time')
        end_time = data.get('end_time')

        if end_time <= start_time:
            raise serializers.ValidationError('End time must be after start time')
        
        return data

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
            'active',
            'finished',
            'created_by',
            'group'
        ]
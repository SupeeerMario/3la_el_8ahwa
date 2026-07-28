from rest_framework import serializers
from .models import Event, EventLocation, LocationVote
from django.utils import timezone


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            'title',
            'text',
            'start_time',
            'end_time',
            'created_at',
            'active',
            'finished'
        ]
        read_only_fields = ['created_at', 'active', 'finished']

    def validate_start_time(self, value):
        if value < timezone.now():
            raise serializers.ValidationError('Start time cannot be in the past')
        return value

    def validate_end_time(self,value):
        if value < timezone.now():
            raise serializers.ValidationError('End time cannot be in the past')
        return value

    def validate(self, data):
        start_time = data.get('start_time') or getattr(self.instance, 'start_time', None)
        end_time = data.get('end_time') or getattr(self.instance, 'end_time', None)

        if start_time and end_time and end_time <= start_time:
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
            'winning_location',
            'start_time',
            'end_time',
            'created_at',
            'active',
            'finished',
            'created_by',
            'group'
        ]


class EventLoctionsSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventLocation
        fields = [
            'id',
            'name',
            'latitude',
            'longitude',
            'created_at'
        ]
        read_only_fields = ['created_at']


class EventLoctionsDetailsSerializer(serializers.ModelSerializer):
    proposed_by = serializers.StringRelatedField()
    vote_count = serializers.SerializerMethodField()
    voted_by = serializers.SerializerMethodField()

    class Meta:
        model = EventLocation
        fields = [
            'id',
            'name',
            'latitude',
            'longitude',
            'proposed_by',
            'vote_count',
            'voted_by',
            'created_at'
        ]
        read_only_fields = ['created_at']

    def get_vote_count(self, obj):
        return len(obj.votes.all())

    def get_voted_by(self, obj):
        return [vote.voted_by.username for vote in obj.votes.all()]



class LocationVoteSerializer(serializers.ModelSerializer):
    class Meta:

        model = LocationVote
        fields = [
            'id',
            'event',
            'location',
            'voted_by',
            'created_at'
        ]

        read_only_fields = ['created_at', 'voted_by', 'event', 'location']
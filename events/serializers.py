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
        # read_only_fields must live inside Meta to take effect.
        # winning_location is intentionally excluded: it is decided by votes,
        # not set by the client.
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
        # On partial updates either bound may be absent; fall back to the
        # instance value so the comparison never hits a None.
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
    # This serializer used to raise on use: it listed a 'vote_by' field that
    # didn't exist and declared `voted_by` with no get_voted_by method. Now it
    # exposes two computed read-only fields backed by the methods below:
    # vote_count (tally) and voted_by (usernames who voted).
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
        return obj.votes.count()

    def get_voted_by(self, obj):
        return [vote.voted_by.username for vote in obj.votes.all()]



class LocationVoteSerializer(serializers.ModelSerializer):
    class Meta:

        model = LocationVote
        fields = [
            'id',
            'location',
            'voted_by',
            'created_at'
        ]
    
        read_only_fields = ['created_at', 'voted_by']
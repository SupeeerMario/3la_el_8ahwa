from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .models import Event, EventLocation, LocationVote
from .serializers import EventSerializer,EventDetailSerializer,EventLoctionsSerializer ,EventLoctionsDetailsSerializer, LocationVoteSerializer
from .voting import tally as vote_tally, voting_open
from groups.models import GroupMember
from core import errors
from core.errors import error_response
from core.permissions import IsEventCreator, IsLocationProposer
from groups import room
from notifications.services import notify_group

# Create your views here.


def _as_int(value):
    """Coerce a request-supplied id to int, or None.

    Ids arrive as raw JSON/query strings. A non-numeric one used to reach the
    ORM directly and raise ValueError -> 500; returning None instead funnels
    garbage into the same 403/404 that a missing id already produced.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

class EventViewSet(ModelViewSet):

    permission_classes = [IsAuthenticated]
    lookup_value_regex = "[0-9]+"

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsEventCreator()]
        return super().get_permissions()

    def get_queryset(self):
        return Event.objects.filter(
            group__members__user = self.request.user
        )


    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return EventDetailSerializer
        return EventSerializer
    
    ## make it so there can be multible places and member can vote for a place
    def create(self, request, *args, **kwargs):
        group_id = _as_int(request.data.get('group_id'))
        current_user = request.user
        

        is_member =  GroupMember.objects.filter(
            user = current_user,
            group=group_id
        ).exists()

        if not is_member:
            return error_response(
                errors.NOT_A_MEMBER,
                'You are not a member of this group',
                status.HTTP_403_FORBIDDEN
            )
        
        
        serializer = self.get_serializer(data = request.data)
        serializer.is_valid(raise_exception = True)
        event = serializer.save(created_by = current_user, group_id = group_id)

        room.event_created(event, current_user)

        notify_group(
            event.group,
            'new_event',
            {
                'event_id': event.id,
                'event_title': event.title,
                'group_id': event.group_id,
                'group_name': event.group.name,
                'start_time': event.start_time.isoformat(),
                'created_by_id': current_user.id,
                'created_by_username': current_user.username,
            },
            exclude=[current_user],
        )

        return Response(
            {'message':'Event created successfully', 'event':serializer.data},
            status=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        event = self.get_object()
        lock = timedelta(minutes=settings.EVENT_DELETE_LOCK_MINUTES)

        if timezone.now() >= event.start_time - lock:
            return error_response(
                errors.EVENT_STARTING_SOON,
                'This event starts too soon to be deleted',
                status.HTTP_400_BAD_REQUEST
            )

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'], url_path='tally')
    def tally(self, request, pk=None):
        event = self.get_object()

        my_vote = LocationVote.objects.filter(
            event=event, voted_by=request.user
        ).values_list('location_id', flat=True).first()

        return Response({
            'event': event.id,
            'voting_open': voting_open(event),
            'winner_frozen': event.winner_frozen,
            'winning_location': event.winning_location_id,
            'my_vote': my_vote,
            'locations': [
                {
                    'id': location.id,
                    'name': location.name,
                    'vote_count': location.vote_count,
                }
                for location in vote_tally(event)
            ],
        })



class EventLocationViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    lookup_value_regex = "[0-9]+"

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsLocationProposer()]
        return super().get_permissions()

    def get_queryset(self):
        qs = EventLocation.objects.filter(
            event__group__members__user = self.request.user
        )

        if self.action in ('list', 'retrieve'):
            qs = qs.select_related('proposed_by').prefetch_related('votes__voted_by')

        if self.action != 'list':
            return qs

        event_id = _as_int(self.request.query_params.get('event'))

        if not event_id:
            return qs.none()
        return qs.filter(event_id = event_id)


    def get_serializer_class(self):

        if self.action in ['list', 'retrieve']:
            return EventLoctionsDetailsSerializer
        
        return EventLoctionsSerializer
        

    def create(self, request, *args, **kwargs):
    
        event_id = _as_int(request.data.get('event_id'))
        current_user = request.user

        try:
            event = Event.objects.get(id = event_id)

        except Event.DoesNotExist:
            return error_response(
                errors.EVENT_NOT_FOUND,
                'Event not found',
                status.HTTP_404_NOT_FOUND
            )
        

        is_member = GroupMember.objects.filter(
            user = current_user,
            group = event.group
        ).exists()

        if not is_member:
            return error_response(
                errors.NOT_A_MEMBER,
                'You are not a member of this group',
                status.HTTP_403_FORBIDDEN
            )
        

        if event.active or event.finished:
            return error_response(
                errors.VOTING_CLOSED,
                'Voting is closed for this event',
                status.HTTP_400_BAD_REQUEST
            )
        

        serializer = self.get_serializer(data = request.data)
        serializer.is_valid(raise_exception = True)
        location = serializer.save(proposed_by = current_user, event = event)

        room.location_proposed(location, current_user)

        return Response(
            {'message':'Location proposed successfully', 'location':serializer.data},
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post', 'delete'], url_path='vote')
    def vote(self, request, pk=None):
        location = self.get_object()
        event = location.event

        if not voting_open(event):
            return error_response(
                errors.VOTING_CLOSED,
                'Voting is closed for this event',
                status.HTTP_400_BAD_REQUEST
            )

        if request.method == 'DELETE':
            deleted, _ = LocationVote.objects.filter(
                location=location, voted_by=request.user
            ).delete()

            if not deleted:
                return error_response(
                    errors.VOTE_NOT_FOUND,
                    'You have not voted for this location',
                    status.HTTP_404_NOT_FOUND
                )

            return Response(status=status.HTTP_204_NO_CONTENT)

        existing = LocationVote.objects.filter(
            event=event, voted_by=request.user
        ).first()

        if existing is not None:
            if existing.location_id == location.id:
                return error_response(
                    errors.ALREADY_VOTED,
                    'You have already voted for this location',
                    status.HTTP_400_BAD_REQUEST
                )

            existing.location = location
            existing.save(update_fields=['location', 'event'])

            room.vote_cast(location, request.user)

            return Response(
                LocationVoteSerializer(existing).data,
                status=status.HTTP_200_OK
            )

        try:
            new_vote = LocationVote.objects.create(
                location=location, voted_by=request.user
            )
        except IntegrityError:
            return error_response(
                errors.ALREADY_VOTED,
                'You have already voted in this event',
                status.HTTP_400_BAD_REQUEST
            )

        room.vote_cast(location, request.user)

        return Response(
            LocationVoteSerializer(new_vote).data,
            status=status.HTTP_201_CREATED
        )






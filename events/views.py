from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .models import Event, EventLocation, LocationVote
from .serializers import EventSerializer,EventDetailSerializer,EventLoctionsSerializer ,EventLoctionsDetailsSerializer, LocationVoteSerializer
from groups.models import GroupMember
from core import errors
from core.errors import error_response
from core.permissions import IsEventCreator, IsLocationProposer

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
        serializer.save(created_by = current_user, group_id = group_id)


        return Response(
            {'message':'Event created successfully', 'event':serializer.data},
            status=status.HTTP_201_CREATED
        )
    


class EventLocationViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsLocationProposer()]
        return super().get_permissions()

    def get_queryset(self):
        qs = EventLocation.objects.filter(
            event__group__members__user = self.request.user
        )

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
        serializer.save(proposed_by = current_user, event = event)

        return Response(
            {'message':'Location proposed successfully', 'location':serializer.data},
            status=status.HTTP_201_CREATED
        )






from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .models import Event, EventLocation, LocationVote
from .serializers import EventSerializer,EventDetailSerializer,EventLoctionsSerializer ,EventLoctionsDetailsSerializer, LocationVoteSerializer
from groups.models import GroupMember
from rest_framework.exceptions import PermissionDenied
from core.permissions import IsEventCreator

# Create your views here.


class EventViewSet(ModelViewSet):

    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]

    def get_permissions(self):
        # Only the creator may edit or delete an event. Enforced on both the
        # update and destroy routes (destroy was previously unguarded, letting
        # any group member delete another member's event).
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsEventCreator()]
        return [IsAuthenticated()]

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
        group_id = request.data.get('group_id')
        current_user = request.user
        

        is_member =  GroupMember.objects.filter(
            user = current_user,
            group=group_id
        ).exists()

        if not is_member:
            raise PermissionDenied('You are not a member of this group')
        
        
        serializer = self.get_serializer(data = request.data)
        serializer.is_valid(raise_exception = True)
        serializer.save(created_by = current_user, group_id = group_id)


        return Response(
            {'message':'Event created successfully', 'event':serializer.data},
            status=status.HTTP_201_CREATED
        )
    


class EventLocationViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]


    def get_queryset(self):
        event_id = self.request.query_params.get('event')
        
        if not event_id:
            return EventLocation.objects.none()
        return EventLocation.objects.filter(event_id = event_id)
    

    def get_serializer_class(self):

        if self.action in ['list', 'retrieve']:
            return EventLoctionsDetailsSerializer
        
        return EventLoctionsSerializer
        

    def create(self, request, *args, **kwargs):
    
        event_id = request.data.get('event_id')
        current_user = request.user

        try:
            event = Event.objects.get(id = event_id)

        except Event.DoesNotExist:
            return Response(
                {'error':'Event not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        

        is_member = GroupMember.objects.filter(
            user = current_user,
            group = event.group
        ).exists()

        if not is_member:
            raise PermissionDenied('You are not a member of this group')
        

        if event.active or event.finished:
            return Response(
                {'error':'Voting is closed for this event'},
                status=status.HTTP_400_BAD_REQUEST
            )
        

        serializer = self.get_serializer(data = request.data)
        serializer.is_valid(raise_exception = True)
        serializer.save(proposed_by = current_user, event = event)

        return Response(
            {'message':'Location proposed successfully', 'location':serializer.data},
            status=status.HTTP_201_CREATED
        )



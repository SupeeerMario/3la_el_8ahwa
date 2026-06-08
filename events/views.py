from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .models import Event
from .serializers import EventSerializer,EventDetailSerializer
from groups.models import GroupMember
from rest_framework.exceptions import PermissionDenied

# Create your views here.


class EventViewSet(ModelViewSet):

    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]

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
    

    ## make it that before the event start time by 30 min it can't be deleted
    def destroy(self, request, *args, **kwargs):
        event = self.get_object()
        current_user = request.user

        if event.created_by != request.user:
            return Response(
                {'error':'Only the event creator can delete this event'},
                status=status.HTTP_403_FORBIDDEN
            ) 
        
        event.delete()
        return Response(
            {'message':'Event deleted successfully'},
            status=status.HTTP_200_OK
        )
    

    ##  make it that before the event start time by 30 min it can't be deleted
    def update(self, request, *args, **kwargs):
        event = self.get_object()
        current_user = request.user


        if event.created_by != current_user:
            return Response(
                {'error':'Only the event creator can update this event'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().update(request, *args, **kwargs)
    


    
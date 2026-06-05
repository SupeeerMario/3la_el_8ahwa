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
        if self.action in ['list', 'retrive']:
            return EventDetailSerializer
        return EventSerializer
    

    def perform_create(self, serializer, pk=None):
        group_id = self.request.data.get('group_id')
        current_user = self.request.user
        
        is_member =  GroupMember.objects.filter(
            user = current_user,
            group=group_id
        ).exists()

        if not is_member:
            return PermissionDenied('You are not a member of this group')
        
        serializer = self.get_serializer(data = self.request.data)
        serializer.is_valid(raise_exception = True)
        serializer.save(created_by = current_user, group_id = group_id)


        return Response(
            {'message':'Event created successfully', 'event':serializer.data},
            status=status.HTTP_201_CREATED
        )
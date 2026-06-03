from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from .models import Group, GroupMember,GroupInvitaion
from .serializers import GroupSerializer, GroupMemberSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.authentication import TokenAuthentication
from rest_framework import status
from django.db.models import Count
# Create your views here.


class GroupsViewSet(ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]

    def get_queryset(self):
        return Group.objects.annotate(members_count = Count('members'))


    @action(
            detail= False,
            methods=['GET'],
            permission_classes = [IsAuthenticated]
    )
    def my_groups(self,request):
        current_user = request.user
        member_group_ids = GroupMember.objects.filter(user = current_user).values_list('group_id', flat=True)
        queryset = self.get_queryset().filter(id__in=member_group_ids)
        serializer = self.get_serializer(queryset, many = True)
        return Response(serializer.data, status=status.HTTP_200_OK)



    @action(
            detail=False,
            methods=['POST'],
            permission_classes=[IsAuthenticated]
    )
    def perform_create(self, request):
        
        serializer = self.get_serializer(data = request.data)

        serializer.is_valid(raise_exception = True)

        group = serializer.save(created_by = self.request.user)
        GroupMember.objects.create(user = self.request.user, group = group, role = 'admin')

        return Response(
            {'message': f'Group is created sucessfully {serializer.data}'},
            status=status.HTTP_201_CREATED
        )



    @action(
        detail=True,
        methods=['POST'],
        permission_classes=[IsAuthenticated]
    )
    def join_group(self, request, pk = None):
        current_user = request.user

        try:
            group = Group.objects.get(pk=pk)

        except Group.DoesNotExist:
            return Response(
                {'error':'Group not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        member, created = GroupMember.objects.get_or_create(
            user = current_user,
            group = group,
            defaults= {'role':'member'}
        )

        if not created:
            return Response(
                {'error':"You are already a membre of this group"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response(
            {'messege':f'Successfully joined group {group.name}'},
            status=status.HTTP_201_CREATED
        )
        
    # make it that if owner leaves the role is transfered to the latest entry
    #if the last member leaves the group the group gets deleted
    @action(
        detail=True,
        methods=['Delete'],
        permission_classes = [IsAuthenticated]
    )
    def leave_group(self, request, pk = None):
        current_user = request.user

        try:
            group = Group.objects.get(pk=pk)

        except Group.DoesNotExist:
            return Response(
                {'error':'Group not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            membreship = GroupMember.objects.get(user = current_user, group=group)

        except GroupMember.DoesNotExist:
            return Response(
                {'error':'You are not a member of this group'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        membreship.delete()
        
        return Response(
            {'message':f'You have successfully left the gruop {group.name}'},
            status=status.HTTP_200_OK
        )
        

    @action(
        detail=True,
        methods=['PUT', 'PATCH'],
        permission_classes = [IsAuthenticated]
    )
    def update_group(self, request, pk=None):
        current_user = request.user
        
        try:
            group = Group.objects.get(pk=pk)
        
        except Group.DoesNotExist:
            return Response(
                {'error':'Group not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        is_admin = GroupMember.objects.filter(
            user = current_user,
            group = group,
            role = 'admin'
        ).exists()

        if not is_admin:
            return Response(
                {'error':'ermission denied. You must be an admin of this group to delete it'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(instance = group, data = request.data, partial = True)
        serializer.is_valid(raise_exception = True)
        serializer.save()
        return Response(
            {'message':'Group has been updated'},
            status=status.HTTP_200_OK
        )


    @action(
        detail=True,
        methods=['DELETE'],
        permission_classes = [IsAuthenticated]
    )
    def delete_group(self, request, pk=None):
        current_user = request.user
        
        try:
            group = Group.objects.get(pk=pk)
        
        except Group.DoesNotExist:
            return Response(
                {'error':'Group not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        is_admin = GroupMember.objects.filter(
            user = current_user,
            group = group,
            role = 'admin'
        ).exists()

        
        if is_admin:
            group.delete()
            return Response(
                {'message':'Group deleted successfully'},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {'error':'Permission denied. You must be an admin of this group to delete it'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        

    @action(
        detail=True,
        methods=['GET'],
        permission_classes = [IsAuthenticated]
    )
    def list_group_members(self,request,pk=None):
        current_user = request.user

        try:
            group = Group.objects.get(pk=pk)
        
        except Group.DoesNotExist:
            return Response(
                {'error':'Group not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            membership = GroupMember.objects.get(user = current_user, group=group)
        
        except GroupMember.DoesNotExist:
            return Response(
                {'error':'You are not a member of this group'},
                status=status.HTTP_400_BAD_REQUEST
            )

        group_members = GroupMember.objects.filter(group = group)
        serializer = GroupMemberSerializer(group_members, many = True)

        return Response(
            {'message':f'Members of the {group.name} are',
            'members': serializer.data
            },
            status=status.HTTP_200_OK
        )



    @action(
        detail=True,
        methods=['POST'],
        permission_classes = [IsAuthenticated]
    )
    def send_invite(self, request, pk=None):
        pass
from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from .models import Group, GroupMember,GroupInvitaion
from .serializers import GroupSerializer, GroupMemberSerializer, GroupInvitaionSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework import status
from django.db.models import Count
from django.contrib.auth import get_user_model
from core.permissions import IsGroupAdmin
# Create your views here.


class GroupsViewSet(ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]
    def get_permissions(self):
        # The default ModelViewSet update/destroy routes must enforce the same
        # admin check as the custom update_group/delete_group actions, otherwise
        # any authenticated user can edit or delete any group via PUT/DELETE.
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsGroupAdmin()]
        return [IsAuthenticated()]

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



    def perform_create(self, serializer):
        # DRF calls perform_create(self, serializer) after validation; the
        # previous signature (self, request) broke group creation entirely.
        # Validation and the 201 response are handled by CreateModelMixin.
        group = serializer.save(created_by=self.request.user)
        GroupMember.objects.create(user=self.request.user, group=group, role="admin")



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





class GroupInvitationViewSet(ModelViewSet):


    serializer_class = GroupInvitaionSerializer
    permission_classes = [IsAuthenticated]

    @action(
            detail=False,
            methods=['GET'],
            permission_classes = [IsAuthenticated]
    )
    def show_all_invitations(self,request):
        current_user = request.user
        invitaitons  = GroupInvitaion.objects.filter(invited_user = current_user)
        serializer = GroupInvitaionSerializer(invitaitons, many = True)
        return Response(
            {'message':'here are all your invites',
            'invites': serializer.data
            },
            status=status.HTTP_200_OK
        )


    @action(
        detail=False,
        methods=['POST'],
        permission_classes = [IsAuthenticated]
    )
    def send_invite(self, request):
        current_user = request.user
        group_id = request.data.get('group_id')
        username_to_invite = request.data.get('username_to_invite')

        try:
            group = Group.objects.get(id = group_id)
        except Group.DoesNotExist:
            return Response(
                {'error':'Group not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        is_admin = GroupMember.objects.filter(user = current_user, group = group, role = 'admin').exists()

        if not is_admin:
            return Response(
                {'error':'only admins can send invites'},
                status=status.HTTP_403_FORBIDDEN
            )


        user_model = get_user_model()

        try:
            invited_user = user_model.objects.get(username = username_to_invite)
        
        except user_model.DoesNotExist:
            return Response(
                {'error':f'{username_to_invite} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if GroupMember.objects.filter(user = invited_user, group = group).exists():
            return Response(
                {'error':f'{username_to_invite} is already a member of this group'},
                status=status.HTTP_400_BAD_REQUEST
            )
        

        invitaion, created = GroupInvitaion.objects.get_or_create(
            group=group,
            invited_user=invited_user,
            defaults={'invited_by':current_user, 'status':'pending'}
        )

        if not created:
            if invitaion.status == 'pending':
                return Response(
                    {'error':'An invitaion is already pending'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            invitaion.status = 'pending'
            invitaion.invited_by = current_user
            invitaion.save()

        serializer = GroupInvitaionSerializer(invitaion)

        return Response(
            {'message':f'invitaion sent to {username_to_invite} sucessfully',
             'invites': serializer.data
             },
            status=status.HTTP_201_CREATED,
        )
    

    




    @action(
        detail=True,
        methods=['POST'],
        permission_classes = [IsAuthenticated]
    )
    def invite_responce(self, request, pk=None):
        invite_action = request.data.get('action')


        if invite_action not in ['accept', 'reject']:
            return Response(
                {'error':'Invalid action, must be accepted or rejected'},
                status= status.HTTP_400_BAD_REQUEST
            )
        

        if invite_action == 'accept':
            return self.accept_invite(request, pk)
        
        else:
            return self.decline_invite(request, pk)


        
        





    @action(
        detail=True,
        methods=['POST'],
        permission_classes = [IsAuthenticated]
    )
    def accept_invite(self, request, pk=None):
        current_user = request.user

        try:
            invitaion = GroupInvitaion.objects.get(pk=pk, invited_user = current_user, status = 'pending')
        
        except GroupInvitaion.DoesNotExist:

            return Response(
                {'error':'pending invitaion not found, or you are not authiriozed to repond'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        invitaion.status = 'accepted'
        invitaion.save()

        GroupMember.objects.get_or_create(
            user = request.user,
            group = invitaion.group,
            defaults={'role':'member'}
        )

        invitaion.delete()

        return Response(
            {'message':f'Sucessfully joined {invitaion.group.name}'},
            status=status.HTTP_200_OK
        )




    @action(
    detail=True,
    methods=['POST'],
    permission_classes = [IsAuthenticated]
    )
    def decline_invite(self, request, pk=None):
        current_user = request.user

        try:
            invitaion = GroupInvitaion.objects.get(pk=pk, invited_user = current_user, status = 'pending')
        
        except GroupInvitaion.DoesNotExist:

            return Response(
                {'error':'pending invitaion not found, or you are not authiriozed to repond'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        invitaion.status = 'rejected'
        invitaion.save()

        return Response(
            {'message':'invitaion declined sucessfully'},
            status=status.HTTP_200_OK
        )
        
from datetime import timedelta

from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from .models import Group, GroupMember,GroupInvitaion, GroupInviteToken, Message
from .serializers import (
    GroupSerializer,
    GroupMemberSerializer,
    GroupInvitaionSerializer,
    GroupInviteTokenSerializer,
    InvitePreviewSerializer,
    MessageSerializer,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import action
from rest_framework import status
from django.db import transaction
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from core import errors, storage
from core.errors import error_response
from core.permissions import IsGroupAdmin
from core.throttling import (
    GroupMessagesThrottle,
    InvitePreviewThrottle,
    JoinGroupThrottle,
    SendInviteThrottle,
)
from . import cursors, invites, room
from notifications.services import notify, notify_group
# Create your views here.


DEFAULT_INVITE_TOKEN_HOURS = 168
MAX_INVITE_TOKEN_HOURS = 720


MESSAGE_PAGE_SIZE = 30
MESSAGE_PAGE_LIMIT = 100


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


INVITE_FAILURE_MESSAGES = {
    errors.INVITE_TOKEN_NOT_FOUND: 'This invite link is not valid',
    errors.INVITE_TOKEN_REVOKED: 'This invite link has been revoked',
    errors.INVITE_TOKEN_EXPIRED: 'This invite link has expired',
    errors.INVITE_TOKEN_EXHAUSTED: 'This invite link has already been used the maximum number of times',
    errors.ALREADY_MEMBER: 'You are already a member of this group',
}


def _reassign_creator(group, departing_user_id):
    if group.created_by_id != departing_user_id:
        return None

    remaining = GroupMember.objects.filter(group=group).exclude(user_id=departing_user_id)
    successor = (
        remaining.filter(role="admin").order_by("joined_at", "id").first()
        or remaining.order_by("joined_at", "id").first()
    )

    group.created_by = successor.user if successor else None
    group.save(update_fields=["created_by"])
    return group.created_by


class GroupsViewSet(ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]
    lookup_value_regex = "[0-9]+"

    def get_permissions(self):
        if self.action in (
            "update",
            "partial_update",
            "destroy",
            "update_group",
            "delete_group",
            "remove_member",
            "change_role",
            "invite_tokens",
            "revoke_invite_token",
            "image_upload_signature",
            "image",
        ):
            return [IsAuthenticated(), IsGroupAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        return Group.objects.filter(
            id__in = GroupMember.objects.filter(
                user = self.request.user
            ).values('group_id')
        ).annotate(members_count = Count('members'))


    @action(
            detail= False,
            methods=['GET'],
            permission_classes = [IsAuthenticated]
    )
    def my_groups(self,request):
        return self.list(request)


    def perform_create(self, serializer):
        group = serializer.save(created_by=self.request.user)
        GroupMember.objects.create(user=self.request.user, group=group, role="admin")



    @action(
        detail=True,
        methods=['Delete'],
        permission_classes = [IsAuthenticated]
    )
    def leave_group(self, request, pk = None):
        current_user = request.user

        with transaction.atomic():
            try:
                group = Group.objects.select_for_update().get(pk=pk)

            except Group.DoesNotExist:
                return error_response(
                    errors.GROUP_NOT_FOUND,
                    'Group not found',
                    status.HTTP_404_NOT_FOUND
                )

            try:
                membreship = GroupMember.objects.get(user = current_user, group=group)

            except GroupMember.DoesNotExist:
                return error_response(
                    errors.NOT_A_MEMBER,
                    'You are not a member of this group',
                    status.HTTP_400_BAD_REQUEST
                )

            was_admin = membreship.role == "admin"
            membreship.delete()

            remaining = GroupMember.objects.filter(group=group)

            if not remaining.exists():
                group_name = group.name
                group.delete()
                return Response(
                    {'message': f'You have left and {group_name} was deleted (no members remained)'},
                    status=status.HTTP_200_OK
                )

            room.member_left(group, current_user)

            new_admin = None
            if was_admin and not remaining.filter(role="admin").exists():
                new_admin = remaining.order_by("-joined_at", "-id").first()
                new_admin.role = "admin"
                new_admin.save(update_fields=["role"])

            _reassign_creator(group, current_user.id)

            if new_admin is not None:
                return Response(
                    {'message': f'You have left {group.name}; admin transferred to {new_admin.user}'},
                    status=status.HTTP_200_OK
                )

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
        return self.partial_update(request, pk=pk)


    @action(
        detail=True,
        methods=['DELETE'],
        permission_classes = [IsAuthenticated]
    )
    def delete_group(self, request, pk=None):
        return self.destroy(request, pk=pk)


    @action(
        detail=True,
        methods=['GET'],
        permission_classes = [IsAuthenticated]
    )
    def list_group_members(self,request,pk=None):
        group = self.get_object()

        group_members = GroupMember.objects.filter(group = group).select_related("user")
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
    def remove_member(self, request, pk=None):
        group = self.get_object()
        user_id = _as_int(request.data.get('user_id'))

        if user_id is None:
            return error_response(
                errors.MISSING_FIELD,
                'user_id is required and must be numeric',
                status.HTTP_400_BAD_REQUEST
            )

        if user_id == request.user.id:
            return error_response(
                errors.CANNOT_TARGET_SELF,
                'Use leave_group to remove yourself from a group',
                status.HTTP_400_BAD_REQUEST
            )

        try:
            membership = GroupMember.objects.get(group = group, user_id = user_id)

        except GroupMember.DoesNotExist:
            return error_response(
                errors.MEMBER_NOT_FOUND,
                'That user is not a member of this group',
                status.HTTP_404_NOT_FOUND
            )

        membership.delete()

        _reassign_creator(group, user_id)

        return Response(
            {'message': 'Member removed from the group'},
            status=status.HTTP_200_OK
        )


    @action(
        detail=True,
        methods=['POST'],
        permission_classes = [IsAuthenticated]
    )
    def change_role(self, request, pk=None):
        group = self.get_object()
        user_id = _as_int(request.data.get('user_id'))
        role = request.data.get('role')

        if user_id is None:
            return error_response(
                errors.MISSING_FIELD,
                'user_id is required and must be numeric',
                status.HTTP_400_BAD_REQUEST
            )

        if role not in dict(GroupMember.ROLE_CHOICES):
            return error_response(
                errors.INVALID_ROLE,
                'role must be admin or member',
                status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            try:
                membership = GroupMember.objects.select_for_update().get(
                    group = group, user_id = user_id
                )

            except GroupMember.DoesNotExist:
                return error_response(
                    errors.MEMBER_NOT_FOUND,
                    'That user is not a member of this group',
                    status.HTTP_404_NOT_FOUND
                )

            if membership.role == role:
                return Response(
                    GroupMemberSerializer(membership).data,
                    status=status.HTTP_200_OK
                )

            demoting_last_admin = (
                membership.role == "admin"
                and role != "admin"
                and not GroupMember.objects.filter(group = group, role = "admin")
                .exclude(pk = membership.pk)
                .exists()
            )

            if demoting_last_admin:
                return error_response(
                    errors.LAST_ADMIN,
                    'A group must keep at least one admin',
                    status.HTTP_400_BAD_REQUEST
                )

            membership.role = role
            membership.save(update_fields=["role"])

        return Response(
            GroupMemberSerializer(membership).data,
            status=status.HTTP_200_OK
        )


    @action(
        detail=True,
        methods=['GET', 'POST'],
        permission_classes = [IsAuthenticated]
    )
    def invite_tokens(self, request, pk=None):
        group = self.get_object()

        if request.method == 'GET':
            tokens = GroupInviteToken.objects.filter(
                group = group, revoked = False, expires_at__gt = timezone.now()
            ).select_related("group", "created_by")
            return Response(
                {'invite_tokens': GroupInviteTokenSerializer(tokens, many = True).data},
                status=status.HTTP_200_OK
            )

        hours = _as_int(request.data.get('expires_in_hours', DEFAULT_INVITE_TOKEN_HOURS))
        max_uses = request.data.get('max_uses')

        if hours is None or hours < 1 or hours > MAX_INVITE_TOKEN_HOURS:
            return error_response(
                errors.VALIDATION_ERROR,
                f'expires_in_hours must be between 1 and {MAX_INVITE_TOKEN_HOURS}',
                status.HTTP_400_BAD_REQUEST
            )

        if max_uses is not None:
            max_uses = _as_int(max_uses)
            if max_uses is None or max_uses < 1:
                return error_response(
                    errors.VALIDATION_ERROR,
                    'max_uses must be a positive integer when supplied',
                    status.HTTP_400_BAD_REQUEST
                )

        invite_token = GroupInviteToken.objects.create(
            group = group,
            created_by = request.user,
            expires_at = timezone.now() + timedelta(hours = hours),
            max_uses = max_uses
        )

        return Response(
            GroupInviteTokenSerializer(invite_token).data,
            status=status.HTTP_201_CREATED
        )


    @action(
        detail=True,
        methods=['POST'],
        permission_classes = [IsAuthenticated]
    )
    def revoke_invite_token(self, request, pk=None):
        group = self.get_object()
        token_id = _as_int(request.data.get('token_id'))

        if token_id is None:
            return error_response(
                errors.MISSING_FIELD,
                'token_id is required and must be numeric',
                status.HTTP_400_BAD_REQUEST
            )

        try:
            invite_token = GroupInviteToken.objects.get(pk = token_id, group = group)

        except GroupInviteToken.DoesNotExist:
            return error_response(
                errors.INVITE_TOKEN_NOT_FOUND,
                'Invite token not found for this group',
                status.HTTP_404_NOT_FOUND
            )

        invite_token.revoked = True
        invite_token.save(update_fields=["revoked"])

        return Response(
            {'message': 'Invite token revoked'},
            status=status.HTTP_200_OK
        )


    @action(
        detail=True,
        methods=['POST'],
        permission_classes = [IsAuthenticated],
        url_path='image_upload_signature'
    )
    def image_upload_signature(self, request, pk=None):
        group = self.get_object()

        if not storage.is_configured():
            return error_response(
                errors.AVATAR_STORAGE_UNCONFIGURED,
                'Image uploads are not available on this deployment',
                status.HTTP_503_SERVICE_UNAVAILABLE
            )

        return Response(storage.upload_signature(storage.GROUPS, group.id))


    @action(
        detail=True,
        methods=['POST', 'DELETE'],
        permission_classes = [IsAuthenticated]
    )
    def image(self, request, pk=None):
        group = self.get_object()

        if not storage.is_configured():
            return error_response(
                errors.AVATAR_STORAGE_UNCONFIGURED,
                'Image uploads are not available on this deployment',
                status.HTTP_503_SERVICE_UNAVAILABLE
            )

        if request.method == 'DELETE':
            if group.image_version:
                group.image_version = None
                group.save(update_fields=['image_version'])
                storage.destroy_image(storage.GROUPS, group.id)
            return Response(GroupSerializer(group).data)

        version = _as_int(request.data.get('version'))

        if version is None or version < 1:
            return error_response(
                errors.MISSING_FIELD,
                'version is required and must be the version Cloudinary returned',
                status.HTTP_400_BAD_REQUEST
            )

        group.image_version = version
        group.save(update_fields=['image_version'])

        return Response(GroupSerializer(group).data)


    @action(
        detail=True,
        methods=['GET', 'POST'],
        permission_classes = [IsAuthenticated],
        throttle_classes = [GroupMessagesThrottle]
    )
    def messages(self, request, pk=None):
        group = self.get_object()

        if request.method == 'POST':
            body = (request.data.get('body') or '').strip()

            if not body:
                return error_response(
                    errors.MISSING_FIELD,
                    'body is required',
                    status.HTTP_400_BAD_REQUEST
                )

            message = Message.objects.create(
                group=group, sender=request.user, kind='user', body=body
            )

            return Response(
                MessageSerializer(message).data,
                status=status.HTTP_201_CREATED
            )

        qs = Message.objects.filter(group=group).select_related('sender')

        before = request.query_params.get('before')
        if before:
            position = cursors.decode(before)
            if position is None:
                return error_response(
                    errors.INVALID_CURSOR,
                    'before is not a cursor this endpoint issued',
                    status.HTTP_400_BAD_REQUEST
                )
            stamp, message_id = position
            qs = qs.filter(
                Q(created_at__lt=stamp)
                | Q(created_at=stamp, id__lt=message_id)
            )

        limit = _as_int(request.query_params.get('limit')) or MESSAGE_PAGE_SIZE
        limit = max(1, min(limit, MESSAGE_PAGE_LIMIT))

        window = list(qs[:limit + 1])
        page = window[:limit]

        return Response({
            'messages': MessageSerializer(page, many=True).data,
            'next_before': cursors.encode(page[-1]) if len(window) > limit else None,
        })


    @action(
        detail=False,
        methods=['GET'],
        permission_classes = [AllowAny],
        authentication_classes = [],
        throttle_classes = [InvitePreviewThrottle],
        url_path='invite/(?P<value>[^/]+)'
    )
    def invite_preview(self, request, value=None):
        invite_token = invites.token_for(value)

        if invite_token is None:
            return error_response(
                errors.INVITE_TOKEN_NOT_FOUND,
                'This invite link is not valid',
                status.HTTP_404_NOT_FOUND
            )

        return Response(InvitePreviewSerializer(invite_token).data)


    @action(
        detail=False,
        methods=['POST'],
        permission_classes = [IsAuthenticated],
        throttle_classes = [JoinGroupThrottle]
    )
    def join(self, request):
        raw_token = request.data.get('token') or request.data.get('code')

        if not raw_token:
            return error_response(
                errors.MISSING_FIELD,
                'token or code is required',
                status.HTTP_400_BAD_REQUEST
            )

        group, failure = invites.redeem(raw_token, request.user)

        if failure is not None:
            return error_response(
                failure,
                INVITE_FAILURE_MESSAGES[failure],
                status.HTTP_404_NOT_FOUND
                if failure == errors.INVITE_TOKEN_NOT_FOUND
                else status.HTTP_400_BAD_REQUEST
            )

        joined = Group.objects.filter(pk = group.pk).annotate(
            members_count = Count('members')
        ).first()

        return Response(
            {'message': f'Sucessfully joined {group.name}',
             'group': GroupSerializer(joined).data
             },
            status=status.HTTP_201_CREATED
        )


class GroupInvitationViewSet(ReadOnlyModelViewSet):


    serializer_class = GroupInvitaionSerializer
    permission_classes = [IsAuthenticated]
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        return GroupInvitaion.objects.filter(
            invited_user = self.request.user
        ).select_related("group", "invited_by", "invited_user")

    @action(
            detail=False,
            methods=['GET'],
            permission_classes = [IsAuthenticated]
    )
    def show_all_invitations(self,request):
        requested_status = request.query_params.get('status', 'pending')
        invitaitons = self.get_queryset()

        if requested_status != 'all':
            if requested_status not in dict(GroupInvitaion.STATUS_CHOICES):
                return error_response(
                    errors.VALIDATION_ERROR,
                    'status must be pending, accepted, rejected or all',
                    status.HTTP_400_BAD_REQUEST
                )
            invitaitons = invitaitons.filter(status = requested_status)

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
        permission_classes = [IsAuthenticated],
        throttle_classes = [SendInviteThrottle]
    )
    def send_invite(self, request):
        current_user = request.user
        group_id = _as_int(request.data.get('group_id'))
        username_to_invite = request.data.get('username_to_invite')

        if group_id is None:
            return error_response(
                errors.MISSING_FIELD,
                'group_id is required and must be numeric',
                status.HTTP_400_BAD_REQUEST
            )

        try:
            group = Group.objects.get(id = group_id, members__user = current_user)
        except Group.DoesNotExist:
            return error_response(
                errors.GROUP_NOT_FOUND,
                'Group not found',
                status.HTTP_404_NOT_FOUND
            )

        is_admin = GroupMember.objects.filter(user = current_user, group = group, role = 'admin').exists()

        if not is_admin:
            return error_response(
                errors.NOT_ADMIN,
                'only admins can send invites',
                status.HTTP_403_FORBIDDEN
            )


        user_model = get_user_model()

        try:
            invited_user = user_model.objects.get(username = username_to_invite)

        except user_model.DoesNotExist:
            return error_response(
                errors.USER_NOT_FOUND,
                f'{username_to_invite} not found',
                status.HTTP_404_NOT_FOUND
            )

        if GroupMember.objects.filter(user = invited_user, group = group).exists():
            return error_response(
                errors.ALREADY_MEMBER,
                f'{username_to_invite} is already a member of this group',
                status.HTTP_400_BAD_REQUEST
            )


        invitaion, created = GroupInvitaion.objects.get_or_create(
            group=group,
            invited_user=invited_user,
            defaults={'invited_by':current_user, 'status':'pending'}
        )

        if not created:
            if invitaion.status == 'pending':
                return error_response(
                    errors.INVITE_PENDING,
                    'An invitaion is already pending',
                    status.HTTP_400_BAD_REQUEST
                )

            invitaion.status = 'pending'
            invitaion.invited_by = current_user
            invitaion.save()

        notify(
            invited_user,
            'group_invite',
            {
                'invitation_id': invitaion.id,
                'group_id': group.id,
                'group_name': group.name,
                'invited_by_id': current_user.id,
                'invited_by_username': current_user.username,
            },
        )

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


        if invite_action in ('accept', 'accepted'):
            return self.accept_invite(request, pk)

        if invite_action in ('reject', 'rejected'):
            return self.decline_invite(request, pk)

        return error_response(
            errors.INVALID_INVITE_ACTION,
            'Invalid action, must be accept or reject',
            status.HTTP_400_BAD_REQUEST
        )


    @action(
        detail=True,
        methods=['POST'],
        permission_classes = [IsAuthenticated]
    )
    def accept_invite(self, request, pk=None):
        current_user = request.user

        with transaction.atomic():
            try:
                invitaion = GroupInvitaion.objects.select_for_update().get(
                    pk=pk, invited_user = current_user, status = 'pending'
                )

            except GroupInvitaion.DoesNotExist:

                return error_response(
                    errors.INVITE_NOT_FOUND,
                    'pending invitaion not found, or you are not authiriozed to repond',
                    status.HTTP_404_NOT_FOUND
                )

            group = invitaion.group
            invited_by = invitaion.invited_by

            GroupMember.objects.get_or_create(
                user = current_user,
                group = group,
                defaults={'role':'member'}
            )

            invitaion.delete()

        room.member_joined(group, current_user)

        notify(
            invited_by,
            'invite_accepted',
            {
                'group_id': group.id,
                'group_name': group.name,
                'user_id': current_user.id,
                'username': current_user.username,
            },
        )

        return Response(
            {'message':f'Sucessfully joined {group.name}'},
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

            return error_response(
                errors.INVITE_NOT_FOUND,
                'pending invitaion not found, or you are not authiriozed to repond',
                status.HTTP_404_NOT_FOUND
            )

        invitaion.status = 'rejected'
        invitaion.save()

        return Response(
            {'message':'invitaion declined sucessfully'},
            status=status.HTTP_200_OK
        )


    @action(
        detail=True,
        methods=['DELETE'],
        permission_classes = [IsAuthenticated]
    )
    def dismiss(self, request, pk=None):
        invitaion = self.get_object()

        if invitaion.status == 'pending':
            return error_response(
                errors.INVITE_NOT_DISMISSABLE,
                'Respond to a pending invitation before dismissing it',
                status.HTTP_400_BAD_REQUEST
            )

        invitaion.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

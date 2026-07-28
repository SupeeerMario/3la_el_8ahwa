from django.conf import settings
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from core import errors, storage
from core.errors import error_response
from core.geo import haversine_meters
from events.models import Event
from events.views import _as_int
from groups import room
from groups.models import GroupMember
from .models import CheckIn
from .serializers import CheckInDetailSerializer, CheckInSerializer

# Create your views here.


class CheckInViewSet(mixins.CreateModelMixin,
                     mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     GenericViewSet):

    permission_classes = [IsAuthenticated]
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        qs = CheckIn.objects.filter(
            event__group__members__user=self.request.user
        ).select_related('user')

        if self.action != 'list':
            return qs

        event_id = _as_int(self.request.query_params.get('event'))

        if event_id is None:
            return qs.filter(user=self.request.user)
        return qs.filter(event_id=event_id)

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return CheckInDetailSerializer
        return CheckInSerializer

    def create(self, request, *args, **kwargs):
        event_id = _as_int(request.data.get('event_id'))
        current_user = request.user

        try:
            event = Event.objects.select_related('winning_location').get(id=event_id)
        except Event.DoesNotExist:
            return error_response(
                errors.EVENT_NOT_FOUND,
                'Event not found',
                status.HTTP_404_NOT_FOUND
            )

        is_member = GroupMember.objects.filter(
            user=current_user,
            group=event.group
        ).exists()

        if not is_member:
            return error_response(
                errors.NOT_A_MEMBER,
                'You are not a member of this group',
                status.HTTP_403_FORBIDDEN
            )

        if not event.active:
            return error_response(
                errors.EVENT_NOT_ACTIVE,
                'This event is not running right now',
                status.HTTP_400_BAD_REQUEST
            )

        if event.winning_location is None:
            return error_response(
                errors.NO_WINNING_LOCATION,
                'This event has no winning location to check in to',
                status.HTTP_400_BAD_REQUEST
            )

        existing = CheckIn.objects.filter(event=event, user=current_user).first()

        if existing is not None and existing.is_valid:
            return error_response(
                errors.ALREADY_CHECKED_IN,
                'You have already checked in to this event',
                status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(existing, data=request.data)
        serializer.is_valid(raise_exception=True)

        radius = settings.CHECKIN_RADIUS_METERS
        distance = haversine_meters(
            serializer.validated_data['latitude'],
            serializer.validated_data['longitude'],
            event.winning_location.latitude,
            event.winning_location.longitude,
        )

        checkin = serializer.save(
            event=event,
            user=current_user,
            is_valid=distance <= radius,
        )

        room.checkin_recorded(checkin, current_user)

        return Response(
            {
                'message': 'Checked in successfully',
                'checkin': serializer.data,
                'distance_m': round(distance),
                'radius_m': radius,
            },
            status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        )

    def _own_checkin(self, request):
        checkin = self.get_object()

        if checkin.user_id != request.user.id:
            return None, error_response(
                errors.NOT_CHECKIN_OWNER,
                'You can only change the photo on your own check-in',
                status.HTTP_403_FORBIDDEN
            )

        if not storage.is_configured():
            return None, error_response(
                errors.AVATAR_STORAGE_UNCONFIGURED,
                'Image uploads are not available on this deployment',
                status.HTTP_503_SERVICE_UNAVAILABLE
            )

        return checkin, None

    @action(detail=True, methods=['post'], url_path='image_upload_signature')
    def image_upload_signature(self, request, pk=None):
        checkin, refusal = self._own_checkin(request)
        if refusal is not None:
            return refusal

        return Response(storage.upload_signature(storage.CHECKINS, checkin.id))

    @action(detail=True, methods=['post', 'delete'], url_path='image')
    def image(self, request, pk=None):
        checkin, refusal = self._own_checkin(request)
        if refusal is not None:
            return refusal

        if request.method == 'DELETE':
            if checkin.image_version:
                checkin.image_version = None
                checkin.save(update_fields=['image_version'])
                storage.destroy_image(storage.CHECKINS, checkin.id)
            return Response(CheckInDetailSerializer(checkin).data)

        version = _as_int(request.data.get('version'))

        if version is None or version < 1:
            return error_response(
                errors.MISSING_FIELD,
                'version is required and must be the version Cloudinary returned',
                status.HTTP_400_BAD_REQUEST
            )

        checkin.image_version = version
        checkin.save(update_fields=['image_version'])

        return Response(CheckInDetailSerializer(checkin).data)

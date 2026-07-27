from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny
from core import errors, storage
from core.errors import error_response
from core.throttling import (
    LoginAccountThrottle,
    LoginIPThrottle,
    PasswordResetEmailThrottle,
    PasswordResetIPThrottle,
)
from rest_framework.response import Response
from rest_framework.decorators import action
from .serializers import (
    ChangePasswordSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserSeriailizer,
    UserRegisterSerializer,
    UserLoginSerializer,
)
from rest_framework import viewsets, status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


# Create your views here.


def _blacklist_outstanding_tokens(user):
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


EMAIL_TAKEN_MESSAGE = "This email is already in use"


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class UserViewSet(viewsets.ViewSet):

    @action(
            detail=False,
            methods=["POST"],
            permission_classes = [AllowAny],
            authentication_classes = []
    )
    def register(self ,request):
        seriailizer = UserRegisterSerializer(data = request.data)
        seriailizer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                user = seriailizer.save()
        except IntegrityError:
            return error_response(
                errors.EMAIL_TAKEN,
                EMAIL_TAKEN_MESSAGE,
                status.HTTP_400_BAD_REQUEST
            )

        return Response({
            'message':'User created successfully',
            'user':UserSeriailizer(user).data,
            },
            status=status.HTTP_201_CREATED
            )



    @action(
            detail=False,
            methods=["POST"],
            permission_classes = [AllowAny],
            authentication_classes = [],
            throttle_classes = [LoginIPThrottle, LoginAccountThrottle]
    )
    def login(self, request):

        seriailizer = UserLoginSerializer(data= request.data)
        seriailizer.is_valid(raise_exception= True)
        user = seriailizer.validated_data["user"]

        if user is None:
            for throttle in (LoginIPThrottle(), LoginAccountThrottle()):
                throttle.record_failure(request, self)
            return error_response(
                errors.INVALID_CREDENTIALS,
                "Invalid credentials",
                status.HTTP_400_BAD_REQUEST
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            "user": UserSeriailizer(user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        })




    # can't update the password
    @action(
            detail=False,
            methods=["PUT"],
            permission_classes = [IsAuthenticated]
    )
    def update_profile(self, request):
        currnt_user = request.user
        serializer = UserSeriailizer(
            instance = currnt_user,
            data = request.data,
            partial = True
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            return error_response(
                errors.EMAIL_TAKEN,
                EMAIL_TAKEN_MESSAGE,
                status.HTTP_400_BAD_REQUEST
            )

        return Response(serializer.data)



    @action(
            detail=False,
            methods=["POST"],
            permission_classes = [IsAuthenticated]
    )
    def change_password(self, request):
        serializer = ChangePasswordSerializer(
            data = request.data,
            context = {"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        _blacklist_outstanding_tokens(user)
        refresh = RefreshToken.for_user(user)
        return Response({
            "message": "Password changed successfully",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        })



    @action(
            detail=False,
            methods=["POST"],
            permission_classes = [AllowAny],
            authentication_classes = [],
            throttle_classes = [PasswordResetIPThrottle, PasswordResetEmailThrottle],
            url_path="password_reset"
    )
    def password_reset(self, request):
        serializer = PasswordResetRequestSerializer(data = request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.get_user()

        if user is not None:
            uid = serializer.uid_for(user)
            token = serializer.token_for(user)
            link = f"{settings.PASSWORD_RESET_DEEP_LINK}?uid={uid}&token={token}"
            send_mail(
                subject="Reset your 3la el 8ahwa password",
                message=(
                    f"Open this link to choose a new password:\n\n{link}\n\n"
                    f"If you did not ask for this, you can ignore this email."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )

        return Response(
            {"message": "If that email has an account, a reset link has been sent"},
            status=status.HTTP_200_OK
        )



    @action(
            detail=False,
            methods=["POST"],
            permission_classes = [AllowAny],
            authentication_classes = [],
            url_path="password_reset_confirm"
    )
    def password_reset_confirm(self, request):
        serializer = PasswordResetConfirmSerializer(data = request.data)

        if not serializer.is_valid():
            if request.data.get("token") and "token" in serializer.errors:
                return error_response(
                    errors.INVALID_RESET_TOKEN,
                    "This reset link is invalid or has expired",
                    status.HTTP_400_BAD_REQUEST
                )
            raise ValidationError(serializer.errors)

        user = serializer.save()
        _blacklist_outstanding_tokens(user)
        return Response(
            {"message": "Password has been reset successfully"},
            status=status.HTTP_200_OK
        )




    @action(
            detail=False,
            methods=["DELETE"],
            permission_classes=[IsAuthenticated]
    )
    def delete_profile(self, request):
        current_user = request.user
        _blacklist_outstanding_tokens(current_user)
        current_user.delete()
        return Response(
            {"message": "Your account has been deleted successfully"},
            status=status.HTTP_200_OK
        )


    @action(
        detail=False,
        methods=["GET"],
        permission_classes = [IsAuthenticated]
    )
    def get_profile(self, request):
        return Response(UserSeriailizer(request.user).data)


    @action(
        detail=False,
        methods=["POST"],
        permission_classes = [IsAuthenticated],
        url_path="avatar_upload_signature"
    )
    def avatar_upload_signature(self, request):
        if not storage.is_configured():
            return error_response(
                errors.AVATAR_STORAGE_UNCONFIGURED,
                "Avatar uploads are not available on this deployment",
                status.HTTP_503_SERVICE_UNAVAILABLE
            )

        return Response(storage.upload_signature(request.user.id))


    @action(
        detail=False,
        methods=["POST", "DELETE"],
        permission_classes = [IsAuthenticated]
    )
    def avatar(self, request):
        current_user = request.user

        if not storage.is_configured():
            return error_response(
                errors.AVATAR_STORAGE_UNCONFIGURED,
                "Avatar uploads are not available on this deployment",
                status.HTTP_503_SERVICE_UNAVAILABLE
            )

        if request.method == "DELETE":
            if current_user.avatar_version:
                current_user.avatar_version = None
                current_user.save(update_fields=["avatar_version"])
                storage.destroy_avatar(current_user.id)
            return Response(UserSeriailizer(current_user).data)

        version = _as_int(request.data.get("version"))

        if version is None or version < 1:
            return error_response(
                errors.MISSING_FIELD,
                "version is required and must be the version Cloudinary returned",
                status.HTTP_400_BAD_REQUEST
            )

        current_user.avatar_version = version
        current_user.save(update_fields=["avatar_version"])

        return Response(UserSeriailizer(current_user).data)

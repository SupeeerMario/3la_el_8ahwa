from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from core.storage import public_url
from .models import User


class PublicUserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'display_name',
            'avatar_url'
        ]

    def get_avatar_url(self, obj):
        return public_url(obj.avatar_path)


def _reject_duplicate_email(email, exclude_pk = None):
    if not email:
        return email

    taken = User.objects.filter(email__iexact = email)
    if exclude_pk is not None:
        taken = taken.exclude(pk = exclude_pk)
    if taken.exists():
        raise serializers.ValidationError("This email is already in use.")
    return email


class UserSeriailizer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'display_name',
            'email',
            'avatar_url'
        ]

    def get_avatar_url(self, obj):
        return public_url(obj.avatar_path)

    def validate_email(self, value):
        return _reject_duplicate_email(
            value,
            exclude_pk = self.instance.pk if self.instance else None
        )


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only = True)
    email = serializers.EmailField(required = True)

    class Meta :
        model = User
        fields = [
            'id',
            'username',
            'email',
            'display_name',
            'password'
        ]

    def validate_email(self, value):
        return _reject_duplicate_email(value)

    def validate(self, attrs):
        candidate = User(
            username = attrs.get("username"),
            email = attrs.get("email")
        )
        try:
            validate_password(attrs["password"], user = candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        user = User.objects.create_user(
            username = validated_data["username"],
            email = validated_data["email"],
            password = validated_data["password"],
            display_name = validated_data.get("display_name", "")
        )
        return user


class UserLoginSerializer(serializers.Serializer):

    identifier = serializers.CharField(required = False)
    username = serializers.CharField(required = False)
    password = serializers.CharField(write_only = True)

    def validate(self, attrs):
        identifier = attrs.get("identifier") or attrs.get("username")

        if not identifier:
            raise serializers.ValidationError(
                {"identifier": "This field is required."}
            )

        username = identifier

        if "@" in identifier:
            match = User.objects.filter(email__iexact = identifier).first()
            if match is not None:
                username = match.username

        attrs["user"] = authenticate(
            username = username,
            password = attrs["password"]
        )

        return attrs


class ChangePasswordSerializer(serializers.Serializer):

    current_password = serializers.CharField(write_only = True)
    new_password = serializers.CharField(write_only = True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        user = self.context["request"].user
        try:
            validate_password(value, user = user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields = ["password"])
        return user


class PasswordResetRequestSerializer(serializers.Serializer):

    email = serializers.EmailField()

    def get_user(self):
        return User.objects.filter(
            email__iexact = self.validated_data["email"],
            is_active = True
        ).first()

    @staticmethod
    def uid_for(user):
        return urlsafe_base64_encode(force_bytes(user.pk))

    @staticmethod
    def token_for(user):
        return default_token_generator.make_token(user)


class PasswordResetConfirmSerializer(serializers.Serializer):

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only = True)

    def validate(self, attrs):
        try:
            pk = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk = pk, is_active = True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                {"token": "This reset link is invalid or has expired."}
            )

        try:
            validate_password(attrs["new_password"], user = user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields = ["password"])
        return user

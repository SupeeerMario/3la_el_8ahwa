from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import User

class UserSeriailizer(serializers.ModelSerializer):
    
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email'
        ]


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only = True)

    class Meta : 
        model = User
        fields = [
            'id',
            'username',
            'email',
            'password'
        ]

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
            password = validated_data["password"]
        )
        return user
    

class UserLoginSerializer(serializers.ModelSerializer):

    username = serializers.CharField()
    password = serializers.CharField()

    class Meta : 
        model = User
        fields = [
            'id',
            'username',
            'email',
            'password'
        ]
    

    def validate(self, attrs):
        
        user = authenticate(
            username = attrs["username"],
            password = attrs["password"]
        )

        if not user:
            raise serializers.ValidationError("invaild credentials")

        attrs["user"] = user

        return attrs
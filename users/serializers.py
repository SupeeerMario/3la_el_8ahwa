from rest_framework import serializers
from django.contrib.auth import authenticate
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
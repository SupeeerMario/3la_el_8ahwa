from rest_framework import  permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import User
from .serializers import UserSeriailizer, UserRegisterSerializer, UserLoginSerializer
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.authtoken.models import Token
from rest_framework.authentication import TokenAuthentication, SessionAuthentication


# Create your views here.

class UserViewSet(viewsets.ViewSet):
    
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    
    @action(
            detail=False,
            methods=["POST"],
            permission_classes = [permissions.AllowAny]
    )
    def register(self ,request):
        seriailizer = UserRegisterSerializer(data = request.data)
        seriailizer.is_valid(raise_exception=True)
        user = seriailizer.save()
        return Response({"user":UserSeriailizer(user).data})



    @action(
            detail=False,
            methods=["POST"],
            permission_classes = [permissions.AllowAny]
    )
    def login(self, request):
        
        seriailizer = UserLoginSerializer(data= request.data)
        seriailizer.is_valid(raise_exception= True)
        user = seriailizer.validated_data["user"]
        if user:
            token, created = Token.objects.get_or_create(user=user)
            return Response({
                "user": UserSeriailizer(user).data,
                "token": token.key
            })
        
        else:
            return Response({'error': 'Invalid credentials'}, status=401)




    # can't update the password
    @action(
            detail=True,
            methods=["PUT"],
            permission_classes = [permissions.AllowAny]
    )
    def update_user(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error":"user not found"},
                status = status.HTTP_404_NOT_FOUND
            )
        serializer = UserSeriailizer(
            instance = user,
            data = request.data,
            partial = True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


    @action(
            detail=True,
            methods=["DELETE"],
            permission_classes=[permissions.AllowAny]
    )
    def delete(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error":"user not found"},
                status= status.HTTP_404_NOT_FOUND
            )
        user.delete()
        return Response(
            {"message": "User deleted successfully"},
            status=status.HTTP_204_NO_CONTENT
        )



    @action(
        detail=False,
        methods=["GET"],
        permission_classes = [permissions.AllowAny]
    )
    def get_uesrs(self, request):
        user = User.objects.all()
        return Response(UserSeriailizer(user, many = True).data)
    

    @action(
        detail=False,
        methods=["GET"],
        permission_classes = [permissions.IsAuthenticated]
    )
    def profile(self, request):
        try:
            return Response(UserSeriailizer(request.user).data)
        except User.DoesNotExist:
            return Response(
                {"error":"User not found"},
                status=status.HTTP_404_NOT_FOUND
            )


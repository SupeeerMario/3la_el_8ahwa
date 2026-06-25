from rest_framework.permissions import IsAuthenticated, AllowAny  
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import User
from .serializers import UserSeriailizer, UserRegisterSerializer, UserLoginSerializer
from rest_framework import viewsets, status
# Switched from rest_framework.authtoken.models.Token to SimpleJWT: login now
# mints a JWT refresh/access pair instead of a stateful DB token.
from rest_framework_simplejwt.tokens import RefreshToken


# Create your views here.

# The per-view authentication_classes was removed: authentication is now set
# globally to JWT in settings.REST_FRAMEWORK, so the viewset inherits it.
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
        user = seriailizer.save()
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
            authentication_classes = []
    )
    def login(self, request):
        
        seriailizer = UserLoginSerializer(data= request.data)
        seriailizer.is_valid(raise_exception= True)
        user = seriailizer.validated_data["user"]
        # The serializer already raises on invalid credentials, so the old
        # `if user / else: return 401` branch was unreachable and was removed.
        # Issue a JWT pair: short-lived access for requests, refresh to renew.
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
        serializer.save()
        return Response(serializer.data)




    
    @action(
            detail=False,
            methods=["DELETE"],
            permission_classes=[IsAuthenticated]
    )
    def delete_profile(self, request):
        current_user = request.user
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

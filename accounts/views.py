from django.core.exceptions import ValidationError, PermissionDenied
from rest_framework import generics, status, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from .userpermissions import IsSuperUser
from payment.models import *

from .serializers import *


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["referral_code_used"] = self.kwargs.get("referral_code_used")
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        user_data = self.get_serializer(user).data
        return Response({
            "message": "Your account was created successfully. Please activate your account using the OTP sent to your email to log in."},
            status=status.HTTP_201_CREATED)


class VerifyCodeView(generics.CreateAPIView):
    serializer_class = VerifyActiveCodeSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "Email verified successfully. Account activated."},
            status=status.HTTP_200_OK
        )


class ResendCodeView(generics.CreateAPIView):
    serializer_class = ResendCodeSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "A new verification code has been sent to your email."}, status=status.HTTP_200_OK)


class ForgotPasswordView(generics.GenericAPIView):
    serializer_class = ForgotPasswordSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "Reset code sent to email."}, status=status.HTTP_200_OK)


class UserRegistrationVerifyCodeView(generics.GenericAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Save activates the user and marks OTP as used
        user = serializer.save()
        
        # Add 1 free analysis to new user's balance
        # analysesBalance.objects.get_or_create(
        #     user=user,
        #     defaults={'balance': 1}
        # )
        # return to access tocken and refresh to the user after activation
        refresh = RefreshToken.for_user(user)

        return Response({"message": "Account activated successfully.",
                         "tokens": {
                             "access": str(refresh.access_token),
                             "refresh": str(refresh)
                         }
                         }, status=status.HTTP_200_OK)


class VerifyCodeView(generics.GenericAPIView):
    serializer_class = VerfifyCodeSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # You can access validated user and code here if needed:
        user = serializer.user
        reset_code = serializer.reset_code

        # Optionally mark the code as not used
        reset_code.is_used = False
        reset_code.save()

        return Response({"message": "Code verified successfully."}, status=status.HTTP_200_OK)


class SetNewPasswordView(generics.GenericAPIView):
    serializer_class = SetNewPasswordSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        user = serializer.user
        refresh = RefreshToken.for_user(user)

        return Response(
            {"message": "Your password has been changed successfully.",
             "tokens": {
                 "access": str(refresh.access_token),
                 "refresh": str(refresh)
             }
             }, status=200)


class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer

    # permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save()

        return Response({"detail": "Password changed successfully."}, status=status.HTTP_200_OK)


class LogoutView(generics.GenericAPIView):
    serializer_class = LogoutSerializer

    # permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refresh_token = serializer.validated_data['refresh']

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Successfully logged out."}, status=status.HTTP_205_RESET_CONTENT)
        except TokenError:
            return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)


class UpdateProfileView(generics.UpdateAPIView):
    serializer_class = UpdateProfileSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_object(self):
        return self.request.user


class UserUpdateView(generics.RetrieveUpdateAPIView):
    queryset = CustomUser.objects.all()
    serializer_class = UserUpdateSerializer
    
    def get_permissions(self):
        # put and patch methods are not allowed for the superuser
        if self.request.method in ['PUT', 'PATCH']:
            self.permission_classes = [IsSuperUser]
        return super().get_permissions()


class UserListView(generics.ListAPIView):
    serializer_class = UserSerializer
    queryset = CustomUser.objects.all()


class UserDetailView(APIView):

    def get(self, request, *args, **kwargs):
        user = request.user
        serializer = UserDetailSerializer(user)
        auto_renewal = Subscription.objects.filter(user=user).first()
        data = {
                "user": serializer.data,
                "balance": analysesBalance.objects.get_or_create(user=user)[0].balance,
                "auto_renew": auto_renewal.auto_renew if auto_renewal else None
        }
        return Response(data, status=status.HTTP_200_OK)


class DeleteAccountView(generics.DestroyAPIView):

    def get_object(self):
        # Get the user making the request
        user = self.request.user
        password = self.request.data.get("password")
        conform_password = self.request.data.get("conform_password")

        # Validate password and conform_password
        if not password or not conform_password:
            raise ValidationError({"detail": "Both password and conform_password are required."})
        if password != conform_password:
            raise ValidationError({"detail": "Passwords do not match."})
        if user.check_password(password) is False:
            raise ValidationError({"detail": "Incorrect password."})
        return user

    # account deletion
    def delete(self, request, *args, **kwargs):
        user = self.get_object()
        user.delete()
        return Response({"detail": "Account deleted successfully."}, status=status.HTTP_204_NO_CONTENT)




class UserDeleteAdminView(generics.DestroyAPIView):
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer
    
    def get_permissions(self):
        # only superuser can delete other users
        if self.request.method == 'DELETE':
            self.permission_classes = [IsSuperUser]
        return super().get_permissions()
    
    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"detail": "User deleted successfully."}, status=status.HTTP_204_NO_CONTENT)
    
class CreateUserView(generics.CreateAPIView):
    serializer_class = CreateUserSerializer
    permission_classes = [IsSuperUser]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        user_data = self.get_serializer(user).data
        return Response({
            "message": "User account created successfully by admin.",
            "user": user_data
        }, status=status.HTTP_201_CREATED)




class ProjectCretientialsView(generics.GenericAPIView):
    queryset = ProjectCretientials.objects.all()
    serializer_class = ProjectCretientialsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        cretientials = ProjectCretientials.objects.first()
        serializer = self.get_serializer(cretientials)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProjectCretientialsDetailView(generics.GenericAPIView):
    serializer_class = ProjectCretientialsSerializer
    permission_classes = [IsSuperUser]
    
    def get_object(self):
        # Get the first object or None
        obj = ProjectCretientials.objects.first()
        return obj
    
    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj:
            serializer = self.get_serializer(obj)
        else:
            serializer = self.get_serializer()
        return Response(serializer.data)
    
    def patch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj:
            # Update existing
            serializer = self.get_serializer(obj, data=request.data, partial=True)
        else:
            # Create new
            serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


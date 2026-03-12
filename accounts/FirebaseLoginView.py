import os
import firebase_admin
from firebase_admin import credentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

cred_path = os.path.join(BASE_DIR, "glowtrack-8bd39-firebase-adminsdk-fbsvc-871e7825e9.json")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)



from rest_framework.views import APIView #type: ignore
from rest_framework.response import Response #type: ignore
from rest_framework import status, permissions #type: ignore
from django.contrib.auth import get_user_model #type: ignore
from rest_framework_simplejwt.tokens import RefreshToken #type: ignore
from firebase_admin import auth as firebase_auth #type: ignore
import firebase_admin  # type: ignore

User = get_user_model()


class FirebaseLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    def post(self, request):
        id_token = request.data.get("token")
        if not id_token:
            return Response({"message": "Token missing"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            decoded_token = firebase_auth.verify_id_token(id_token)
            email = decoded_token.get("email")
            username = email.split("@")[0]

            # Create or get user
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": username,
                    "is_active": True
                }
            )

            # Generate JWT token
            refresh = RefreshToken.for_user(user)
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name
                }
            })

        except firebase_admin.exceptions.FirebaseError:
            return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)
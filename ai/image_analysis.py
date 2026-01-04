import os
import requests
from rest_framework import status
from rest_framework import permissions
from ai.models import ImageAnalysisResult
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import ImageAnalysisResultSerializer
from payment.utils import deduct_analysis
from payment.models import AnalysisCreditTransaction, OneTimePaymentTransaction, analysesBalance
from payment.paymentpermission import HasActiveSubscription
from django.db import transaction
from django.utils import timezone
from django.db.models import Q


class ImageAnalysis(APIView):
    permission_classes = [permissions.IsAuthenticated, HasActiveSubscription]

    def post(self, request, *args, **kwargs):

        try:
            balance_obj = analysesBalance.objects.get(user=request.user)
        except analysesBalance.DoesNotExist:
            return Response({
                "message": "No active subscription",
                "details": "Please subscribe to a plan to use this feature"
            }, status=402)

        user_credits_this_month = AnalysisCreditTransaction.objects.filter(
            user=request.user,
            type="subscription",
            created_at__month=timezone.now().month,
            created_at__year=timezone.now().year
            )
        user_credits_onetime = OneTimePaymentTransaction.get_balance_for_user(user = request.user)
        
        if user_credits_this_month.exists():
            if user_credits_onetime == 0:
                return Response({
                    "message": "Monthly analysis credit already used",
                    "details": "You have already used your monthly analysis credit. Please purchase one-time credits for extra analyses."
                }, status=402)


        if not balance_obj.balance > 0:
            return Response({
                "message": "Insufficient analysis credits",
                "details": "Please subscribe or upgrade your plan"
            }, status=402)

        image = request.FILES.get("image")
        if not image:
            return Response({"message": "No image provided"}, status=400)

        BASE_URL_AI = os.getenv("BASE_URL_AI")

        ai_response = requests.post(
            BASE_URL_AI,
            files={"file": (image.name, image.read(), image.content_type)}
        )

        if ai_response.status_code != 200:
            return Response({
                "message": "AI error",
                "details": ai_response.text
            }, status=500)

        data = ai_response.json()

        if data.get("face") == 0:
            return Response({
                "message": "Invalid face. Please upload a real human face."
            }, status=400)

        # Everything succeeded → now deduct safely
        with transaction.atomic():
            if data.get("face") == 1:
                if user_credits_this_month.exists():
                    OneTimePaymentTransaction.objects.create(
                        user=request.user,
                        credits=1,
                        type="use"
                    )
                balance_obj.balance -= 1
                balance_obj.save()
                # create a transaction record
                AnalysisCreditTransaction.objects.create(
                    user=request.user
                    )

            payload = {
                "user": request.user.id,
                "face": data["face"],
                "ratings": data["ratings"],
                "key_strengths": data["key_strengths"],
                "exercise_guidance": data["exercise_guidance"],
                "ai_recommendations": data["ai_recommendations"],
            }

            serializer = ImageAnalysisResultSerializer(data=payload)
            serializer.is_valid(raise_exception=True)
            serializer.save()

        return Response({
            "message": "Image analyzed & saved",
            "data": serializer.data
        })


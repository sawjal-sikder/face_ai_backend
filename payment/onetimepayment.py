from rest_framework.views import APIView #type: ignore
from rest_framework.permissions import IsAuthenticated #type: ignore
from rest_framework.response import Response #type: ignore
from .models import OneTimePaymentTransaction, Subscription
import stripe #type: ignore
import os
from django.conf import settings #type: ignore




stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


class PurchaseOneTimeCreditsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            num_credits = int(request.data.get("num_credits", 0))
        except (TypeError, ValueError):
            return Response({"message": "num_credits must be an integer"}, status=400)

        if num_credits <= 0:
            return Response({"message": "Invalid number of credits"}, status=400)

        PRICE_PER_CREDIT = 7  # EUR
        amount = PRICE_PER_CREDIT * num_credits

        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                customer_email=request.user.email,
                line_items=[
                    {
                        "price_data": {
                            "currency": "eur",
                            "unit_amount": PRICE_PER_CREDIT * 100,
                            "product_data": {
                                "name": f"{num_credits} Analysis Credits",
                                "description": "One-time credit purchase",
                            },
                        },
                        "quantity": num_credits,
                    }
                ],
                success_url=os.getenv("BASE_URL_FRONTEND"),
                cancel_url=os.getenv("BASE_URL_FRONTEND"),
                metadata={
                    "user_id": request.user.id,
                    "num_credits": num_credits,
                    "type": "one_time_credits",
                },
            )

            return Response(
                {
                    "checkout_url": session.url,
                    "amount": amount,
                    "currency": "eur",
                    "num_credits": num_credits,
                },
                status=200,
            )

        except stripe.error.StripeError as e:
            return Response({"message": str(e)}, status=400)
from rest_framework.views import APIView #type: ignore
from rest_framework import generics, permissions #type: ignore
from rest_framework.response import Response #type: ignore
from .models import StripePlan, Subscription

import stripe #type: ignore
import os

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

class CreateSubscriptionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        plan_id = request.data.get("plan_id")
        success_url = os.getenv("BASE_URL_FRONTEND") + "/"
        cancel_url = os.getenv("BASE_URL_FRONTEND") + "/"
        
        if not plan_id:
            return Response({"message": "plan_id is required"}, status=400)
        
        # check existing stripe_customer_id for user
        try:
            subscription = Subscription.objects.filter(user=request.user).latest('id')
            stripe_customer_id = subscription.stripe_customer_id
        except Subscription.DoesNotExist:
            stripe_customer_id = None
        
        # Check if the plan_id is valid
        try:
            stripe_plan =StripePlan.objects.get(id=plan_id)
        except StripePlan.DoesNotExist:
            return Response({"message": "Invalid plan_id"}, status=400)
            
        
        # create checkout session
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                payment_method_types=["card"],
                customer_email=request.user.email,
                line_items=[
                    {
                        "price": stripe_plan.stripe_price_id,
                        "quantity": 1,
                    }
                ],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": request.user.id,
                    "plan_id": plan_id,
                    "credits": stripe_plan.credits,
                    "type": "subscription",
                },
            )
            return Response({
                "checkout_url": session.url,
                "session_id": session.id,
                "amount": stripe_plan.amount,
                "plan_name": stripe_plan.name,
                "credits": stripe_plan.credits,
            })
        except Exception as e:
            print(f"Error creating Stripe checkout session: {e}")
            return Response({"message": "Failed to create checkout session"}, status=500)
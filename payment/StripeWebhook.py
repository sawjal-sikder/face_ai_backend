from rest_framework.views import APIView #type: ignore
from rest_framework.response import Response #type: ignore
from .models import Subscription, StripePlan, AnalysisCreditTransaction
import stripe #type: ignore
import os
import logging

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")


class StripeWebhookView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=WEBHOOK_SECRET
            )
            print(f"[INFO] Stripe webhook received: {event['type']}")
        except ValueError:
            print("[ERROR] Invalid payload in Stripe webhook")
            return Response({"message": "Invalid payload"}, status=400)
        except stripe.error.SignatureVerificationError:
            print("[ERROR] Invalid signature in Stripe webhook")
            return Response({"message": "Invalid signature"}, status=400)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            print(f"[DEBUG] Session object: {session}")

            session_metadata = getattr(session, "metadata", None)
            if hasattr(session_metadata, "to_dict"):
                metadata = session_metadata.to_dict()
            elif isinstance(session_metadata, dict):
                metadata = session_metadata
            else:
                metadata = {}

            print(f"[DEBUG] Metadata: {metadata}")

            raw_plan_id = metadata.get("plan_id")
            raw_user_id = metadata.get("user_id")
            raw_credits = metadata.get("credits", 0)

            if not raw_plan_id or not raw_user_id:
                print("[WARNING] Missing plan_id or user_id in metadata")
                return Response({"message": "Missing plan_id or user_id in metadata"}, status=400)

            try:
                plan_id = int(raw_plan_id)
                user_id = int(raw_user_id)
                credits = int(raw_credits)
            except (ValueError, TypeError) as e:
                print(f"[ERROR] Invalid metadata values: {e}")
                return Response({"message": "Invalid metadata values"}, status=400)

            try:
                stripe_plan = StripePlan.objects.get(id=plan_id)

                Subscription.objects.create(
                    user_id=user_id,
                    stripe_customer_id=getattr(session, "customer", None),
                    stripe_subscription_id=getattr(session, "subscription", None),
                    plan=stripe_plan,
                )

                AnalysisCreditTransaction.objects.create(
                    user_id=user_id,
                    credits=credits,
                    type="purchase",
                    reason=f"Subscription purchase - {stripe_plan.name}",
                )

                print(f"[INFO] Subscription and credit transaction created for user {user_id}")

            except StripePlan.DoesNotExist:
                print(f"[ERROR] Invalid plan_id: {plan_id}")
                return Response({"message": "Invalid plan_id"}, status=400)
            except Exception as e:
                print(f"[ERROR] Unexpected error: {e}")
                return Response({"message": "Internal server error"}, status=500)

        elif event["type"].startswith("customer."):
            print(f"[INFO] Customer event received: {event['type']}")

        elif event["type"].startswith("invoice."):
            print(f"[INFO] Invoice event received: {event['type']}")

        else:
            print(f"[INFO] Unhandled Stripe event type: {event['type']}")

        return Response({"status": "success"}, status=200)
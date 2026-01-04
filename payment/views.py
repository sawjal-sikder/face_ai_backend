import os
import stripe
import logging
import datetime
from .models import *
from .serializers import *
from .utils import update_user_analysis_balance
from django.conf import settings
from rest_framework import status
from django.utils import timezone
from rest_framework import generics
from django.http import HttpResponse
from rest_framework import permissions
from rest_framework.views import APIView
from django.utils.timezone import make_aware
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.views.decorators.csrf import csrf_exempt

from dotenv import load_dotenv

# Configure logging
logger = logging.getLogger(__name__)

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

User = get_user_model()

def process_referral_benefits(user, subscription):

    try:
        
        # Check if the user was referred by someone
        if user.referred_by:
            try:
                # Find the referrer
                referrer = User.objects.get(referral_code=user.referred_by)
                
                # Use current time if current_period_end is not available
                base_time = subscription.current_period_end or timezone.now()
                
                # Calculate benefit duration (e.g., 30 days from subscription end)
                benefit_duration = datetime.timedelta(days=30)
                
                # Grant benefits to the referrer
                referrer.is_unlimited = True
                referrer.package_expiry = base_time + benefit_duration
                referrer.save()
                
                # Grant benefits to the referee (the purchaser)
                bonus_duration = datetime.timedelta(days=7)
                user.is_unlimited = True
                user.package_expiry = base_time + bonus_duration
                user.save()
                
            except User.DoesNotExist:
                return Response({"error": "Referrer not found"}, status=404)
            except Exception as inner_e:
                return Response({"error": f"Error processing referral benefits: {str(inner_e)}"}, status=500)
                
        else:
            return Response({"message": "User was not referred by anyone"}, status=200)
            
    except Exception as e:
        return Response({"error": f"Error in referral processing: {str(e)}"}, status=500)



class PlanListCreateView(generics.ListCreateAPIView):
    queryset = Plan.objects.filter(active=True)
    serializer_class = PlanSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):

        name = request.data.get("name")
        interval = request.data.get("interval")  
        amount_eur = request.data.get("amount")  
        if amount_eur is not None:
          try:
            amount = int(float(amount_eur) * 100) 
          except ValueError:
            return Response({"error": "Invalid amount format"}, status=400)
        else:
          amount = None
        trial_days = request.data.get("trial_days", 0)
        analyses_per_interval = request.data.get("analyses_per_interval", 0)

        if not all([name, interval, amount]):
            return Response({"error": "name, interval, amount required"}, status=400)

        try:
            product = stripe.Product.create(name=name)

            price = stripe.Price.create(
                product=product.id,
                unit_amount=int(amount),
                currency="eur",
                recurring={"interval": interval},
            )

            plan = Plan.objects.create(
                  name=name,
                  stripe_product_id=product.id,
                  stripe_price_id=price.id,
                  amount=int(amount),
                  interval=interval,
                  trial_days=trial_days,
                  analyses_per_interval=int(analyses_per_interval),
                  active=True
                  )


            serializer = self.get_serializer(plan)
            return Response(serializer.data, status=201)

        except Exception as e:
            return Response({"error": str(e)}, status=400)



class PlanUpdateView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Plan.objects.all()
    serializer_class = PlanUpdateSerializer
    lookup_field = "id"

    def perform_update(self, serializer):
        plan = self.get_object()
        old_amount = getattr(plan, "amount", None)
        updated_plan = serializer.save()

        try:
            # Update Stripe Product name
            stripe.Product.modify(
                plan.stripe_product_id,
                name=updated_plan.name
            )

            # If amount changed, create a new Stripe Price
            if (
                "amount" in self.request.data
                and int(self.request.data["amount"]) != old_amount
            ):
                new_price = stripe.Price.create(
                    product=plan.stripe_product_id,
                    unit_amount=int(self.request.data["amount"]),
                    currency="eur",
                    recurring={"interval": updated_plan.interval}
                )
                updated_plan.stripe_price_id = new_price.id
                updated_plan.save()

        except Exception as e:
            print("Stripe update error:", e)

    def perform_destroy(self, instance):
        """Delete Stripe product + local Plan"""
        try:
            # 1. Deactivate the Stripe Product
            stripe.Product.modify(
                instance.stripe_product_id,
                active=False
            )

            # 2. Deactivate all Stripe Prices under this product
            prices = stripe.Price.list(product=instance.stripe_product_id)
            for price in prices:
                stripe.Price.modify(price.id, active=False)

        except Exception as e:
            print("Stripe delete error:", e)

        # Delete local Plan
        instance.delete()

    def delete(self, request, *args, **kwargs):
        """Return custom message after delete"""
        plan = self.get_object()
        self.perform_destroy(plan)
        return Response(
            {"message": "Plan deleted successfully"},
            status=status.HTTP_200_OK
        )




class CreateSubscriptionView(APIView):
    def post(self, request):
        plan_id = request.data.get("plan_id")  
        success_url = os.getenv("BASE_URL_FRONTEND", "http://localhost:3000/")
        cancel_url = os.getenv("BASE_URL_FRONTEND", "http://localhost:3000/")
        
        try:
            plan = Plan.objects.get(pk=plan_id, active=True)
        except Plan.DoesNotExist:
            return Response({"error": "Plan not found"}, status=404)

        # Check for existing subscription first
        existing_subscription = Subscription.get_user_active_subscription(request.user)
        
        if existing_subscription:
            # Check user's analysis balance and unlimited status
            balance_obj = None
            has_balance = False
            is_unlimited = False
            
            try:
                balance_obj = analysesBalance.objects.get(user=request.user)
                has_balance = balance_obj.balance > 0
                is_unlimited = balance_obj.balance >= 999999
            except analysesBalance.DoesNotExist:
                pass
            
            # Only allow purchase if balance is 0 and is_unlimited is false
            if has_balance or is_unlimited:
                error_data = {
                    "error": "You already have an active subscription",
                    "message": "You cannot create a new subscription while you have an active plan",
                    "balance": balance_obj.balance if balance_obj else 0,
                    "is_unlimited": is_unlimited,
                    "current_plan": existing_subscription.plan.name if existing_subscription.plan else "Unknown",
                    "status": existing_subscription.status,
                    "subscription_id": existing_subscription.id,
                    "current_period_end": existing_subscription.current_period_end
                }
                
                return Response(error_data, status=400)

        try:
            # Create or get Stripe customer
            customer = None
            existing_sub = Subscription.objects.filter(user=request.user).first()
            
            if existing_sub and existing_sub.stripe_customer_id:
                # Use existing customer
                customer_id = existing_sub.stripe_customer_id
                customer = stripe.Customer.retrieve(customer_id)
            else:
                # Create new customer
                customer = stripe.Customer.create(
                    email=request.user.email,
                    name=getattr(request.user, "full_name", None) or request.user.email,
                    metadata={
                        "user_id": request.user.id,
                        "plan_id": plan.id
                    }
                )

            # Create Stripe Checkout Session
            checkout_session = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=['card'],
                line_items=[{
                    'price': plan.stripe_price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                subscription_data={
                    'metadata': {
                        'user_id': request.user.id,
                        'plan_id': plan.id,
                    }
                },
                metadata={
                    'user_id': request.user.id,
                    'plan_id': plan.id,
                },
                # Enable automatic tax calculation (optional)
                automatic_tax={'enabled': False},
                # Customer can update payment method
                allow_promotion_codes=True,
            )

            #  Save pending subscription in DB (will be updated by webhook)
            subscription = Subscription.objects.create(
                user=request.user,
                plan=plan,
                stripe_customer_id=customer.id,
                stripe_subscription_id=None,  
                status="pending",  
                trial_end=None,  
                current_period_end=None,  
            )

            return Response({
                "checkout_url": checkout_session.url,
                "checkout_session_id": checkout_session.id,
                "subscription_id": subscription.id,
                "plan": plan.name,
                "trial_days": plan.trial_days,
                "message": f"Redirecting to Stripe checkout with {plan.trial_days} days trial period"
            }, status=201)

        except stripe.error.StripeError as e:
            return Response({"error": f"Stripe error: {str(e)}"}, status=400)
        except KeyError as e:
            return Response({"error": f"Missing field: {str(e)}"}, status=400)
        except Exception as e:
            return Response({"error": str(e)}, status=400)


class CheckoutSessionStatusView(APIView):
    """Check the status of a Stripe checkout session"""
    def get(self, request):
        session_id = request.query_params.get('session_id')
        
        if not session_id:
            return Response({"error": "session_id is required"}, status=400)
        
        try:
            # Retrieve the checkout session from Stripe
            session = stripe.checkout.Session.retrieve(session_id)
            
            if session.payment_status == 'paid' and session.subscription:
                # Get the subscription from Stripe
                stripe_subscription = stripe.Subscription.retrieve(session.subscription)
                
                # Update our database subscription
                user_id = session.metadata.get('user_id')
                if user_id:
                    subscription = Subscription.objects.filter(
                        user_id=user_id,
                        status='pending'
                    ).first()
                    
                    if subscription:
                        # Safely get subscription data
                        trial_end = None
                        current_period_end = None
                        
                        # Get trial_end from subscription level
                        trial_end_timestamp = stripe_subscription.get('trial_end')
                        if trial_end_timestamp:
                            trial_end = make_aware(
                                datetime.datetime.fromtimestamp(trial_end_timestamp)
                            )
                        
                        # Get current_period_end from items (not at subscription level)
                        items = stripe_subscription.get('items', {})
                        if items and items.get('data'):
                            first_item = items['data'][0]
                            current_period_end_timestamp = first_item.get('current_period_end')
                            if current_period_end_timestamp:
                                current_period_end = make_aware(
                                    datetime.datetime.fromtimestamp(current_period_end_timestamp)
                                )
                        
                        subscription.stripe_subscription_id = stripe_subscription.id
                        subscription.status = stripe_subscription.get('status', 'active')
                        subscription.trial_end = trial_end
                        subscription.current_period_end = current_period_end
                        subscription.save()
                        
                        return Response({
                            "success": True,
                            "subscription": {
                                "id": subscription.id,
                                "status": subscription.status,
                                "trial_end": subscription.trial_end,
                                "current_period_end": subscription.current_period_end,
                                "plan_name": subscription.plan.name
                            }
                        }, status=200)
            
            return Response({
                "success": False,
                "payment_status": session.payment_status,
                "session_status": session.status
            }, status=200)
            
        except stripe.error.StripeError as e:
            return Response({"error": f"Stripe error: {str(e)}"}, status=400)
        except Exception as e:
            return Response({"error": str(e)}, status=400)


class UserSubscriptionStatusView(APIView):
    """Get current user's subscription status"""
    def get(self, request):
        try:
            active_subscription = Subscription.get_user_active_subscription(request.user)
            
            if not active_subscription:
                return Response({
                    "has_subscription": False,
                    "message": "No active subscription found"
                }, status=200)
            
            return Response({
                "has_subscription": True,
                "subscription": {
                    "id": active_subscription.id,
                    "plan_name": active_subscription.plan.name if active_subscription.plan else "Unknown",
                    "status": active_subscription.status,
                    "is_trial": active_subscription.is_trial(),
                    "is_paid_active": active_subscription.is_paid_active(),
                    "trial_end": active_subscription.trial_end,
                    "current_period_end": active_subscription.current_period_end,
                    "created_at": active_subscription.created_at
                }
            }, status=200)
            
        except Exception as e:
            return Response({"error": str(e)}, status=400)


class PaymentSuccessView(APIView):
    permission_classes = [permissions.AllowAny]
    """Handle successful payment completion"""
    def get(self, request):
        return Response({"message": "Payment successful"}, status=200)


class PaymentCancelView(APIView):
      permission_classes = [permissions.AllowAny]
      """Handle cancelled payment"""
      def get(self, request):
            return Response({"message": "Payment cancel"}, status=200)


class TestReferralBenefitsView(APIView):
    """Test endpoint to verify referral benefits functionality"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """
        Test referral benefits processing
        Usage: POST /api/payment/test-referral-benefits/
        Body: {"subscription_id": <subscription_id>}
        """
        subscription_id = request.data.get("subscription_id")
        
        if not subscription_id:
            return Response({"error": "subscription_id is required"}, status=400)
        
        try:
            subscription = Subscription.objects.get(id=subscription_id)
            
            # Process referral benefits for testing
            process_referral_benefits(subscription.user, subscription)
            
            # Return current user status
            user = subscription.user
            referrer = None
            if user.referred_by:
                try:
                    referrer = User.objects.get(referral_code=user.referred_by)
                except User.DoesNotExist:
                    pass
            
            return Response({
                "message": "Referral benefits processed successfully",
                "purchaser": {
                    "id": user.id,
                    "email": user.email,
                    "is_unlimited": user.is_unlimited,
                    "package_expiry": user.package_expiry,
                    "referred_by": user.referred_by
                },
                "referrer": {
                    "id": referrer.id if referrer else None,
                    "email": referrer.email if referrer else None,
                    "is_unlimited": referrer.is_unlimited if referrer else None,
                    "package_expiry": referrer.package_expiry if referrer else None,
                    "referral_code": referrer.referral_code if referrer else None
                } if referrer else None,
                "subscription": {
                    "id": subscription.id,
                    "status": subscription.status,
                    "current_period_end": subscription.current_period_end,
                    "trial_end": subscription.trial_end
                }
            }, status=200)
            
        except Subscription.DoesNotExist:
            return Response({"error": "Subscription not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)


class CheckReferralStatusView(APIView):
    """Check current user's referral status and benefits"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get current user's referral status"""
        user = request.user
        
        # Count referrals made by this user
        referral_count = User.objects.filter(referred_by=user.referral_code).count()
        
        # Get referrer info if user was referred
        referrer = None
        if user.referred_by:
            try:
                referrer = User.objects.get(referral_code=user.referred_by)
            except User.DoesNotExist:
                pass
        
        return Response({
            "user": {
                "id": user.id,
                "email": user.email,
                "referral_code": user.referral_code,
                "my_referral_link": user.my_referral_link,
                "referred_by": user.referred_by,
                "is_unlimited": user.is_unlimited,
                "package_expiry": user.package_expiry,
                "favorite_item": user.favorite_item,
                "referral_count": referral_count
            },
            "referrer": {
                "id": referrer.id if referrer else None,
                "email": referrer.email if referrer else None,
                "referral_code": referrer.referral_code if referrer else None
            } if referrer else None,
            "referred_users": [
                {
                    "id": ref_user.id,
                    "email": ref_user.email,
                    "is_active": ref_user.is_active
                }
                for ref_user in User.objects.filter(referred_by=user.referral_code)
            ]
        }, status=200)


class WebhookTestView(APIView):
    """Test webhook endpoint to verify it's accessible"""
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        return Response({
            "status": "ok",
            "message": "Webhook endpoint is accessible",
            "timestamp": timezone.now().isoformat(),
            "webhook_url": request.build_absolute_uri('/api/payment/webhook/'),
            "environment": {
                "stripe_secret_configured": bool(os.getenv("STRIPE_SECRET_KEY")),
                "webhook_secret_configured": bool(os.getenv("STRIPE_WEBHOOK_SECRET"))
            }
        }, status=200)
    
    def post(self, request):
        return Response({
            "status": "ok",
            "message": "POST request received successfully",
            "timestamp": timezone.now().isoformat(),
            "content_type": request.content_type,
            "has_body": bool(request.body)
        }, status=200)



@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    
    if not sig_header:
        return HttpResponse("Missing signature", status=400)
    
    if not endpoint_secret:
        return HttpResponse("Webhook secret not configured", status=500)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError as e:
        return HttpResponse("Invalid payload", status=400)
    except stripe.error.SignatureVerificationError as e:
        return HttpResponse("Invalid signature", status=400)
    except Exception as e:
        return HttpResponse("Webhook error", status=400)

    try:
        # Save webhook event to database for audit trail
        webhook_event = WebhookEvent.objects.create(
            event_id=event["id"],
            type=event["type"],
            data=event["data"]["object"],
        )
        
    except Exception as e:
        logger.error(f"⚠️ Failed to save webhook event: {str(e)}")
        # Don't return error here, continue processing

    obj = event["data"]["object"]
    event_type = event["type"]
    
    
    # Determine if this is a payment-related event
    payment_events = [
        "checkout.session.completed",
        "payment_intent.succeeded",
        "payment_intent.payment_failed",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
        "charge.succeeded",
        "charge.failed"
    ]
    
    subscription_events = [
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.trial_will_end"
    ]
    
    if event_type in payment_events:
        print(f"✅ PAYMENT EVENT:  - Payment Status: {obj.get('payment_status', 'N/A')}")
    elif event_type in subscription_events:
        print(f"📋 SUBSCRIPTION EVENT:  - Status: {obj.get('status', 'N/A')}")
    else:
        print(f"ℹ️ OTHER EVENT:  - Not a direct payment event")

    try:
        
        if event_type == "checkout.session.completed":
            
            # Get user from metadata
            metadata = obj.get("metadata", {})
            user_id = metadata.get("user_id")
            plan_id = metadata.get("plan_id")
            
            if user_id and obj.get("subscription"):
                try:
                    # Retrieve the subscription from Stripe
                    stripe_subscription = stripe.Subscription.retrieve(obj["subscription"])
                    
                    # Update the pending subscription in our database
                    subscription = Subscription.objects.filter(
                        user_id=user_id,
                        status="pending"
                    ).first()
                    
                    # If no pending subscription, try to get any subscription for this user
                    if not subscription:
                        subscription = Subscription.objects.filter(
                            user_id=user_id,
                            stripe_subscription_id__isnull=True
                        ).first()
                    
                    if subscription:
                        # Safely handle timestamps
                        trial_end = None
                        current_period_end = None
                        
                        # Get trial_end from subscription level
                        trial_end_timestamp = stripe_subscription.get('trial_end')
                        if trial_end_timestamp:
                            trial_end = make_aware(
                                datetime.datetime.fromtimestamp(trial_end_timestamp)
                            )
                        
                        # Get current_period_end from items (not at subscription level)
                        items = stripe_subscription.get('items', {})
                        if items and items.get('data'):
                            first_item = items['data'][0]
                            current_period_end_timestamp = first_item.get('current_period_end')
                            if current_period_end_timestamp:
                                current_period_end = make_aware(
                                    datetime.datetime.fromtimestamp(current_period_end_timestamp)
                                )
                        
                        subscription.stripe_subscription_id = stripe_subscription.id
                        subscription.status = stripe_subscription.get('status', 'active')
                        subscription.trial_end = trial_end
                        subscription.current_period_end = current_period_end
                        subscription.save()
                        
                        
                        # Process referral benefits after successful subscription creation
                        try:
                            user = User.objects.get(id=user_id)
                            process_referral_benefits(user, subscription)
                        except User.DoesNotExist:
                            logger.error(f"❌ User with id {user_id} not found for referral processing")
                        except Exception as e:
                            logger.error(f"❌ Error in referral processing: {str(e)}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                        
                        # Update analysis balance after successful subscription
                        try:
                            if subscription.plan:
                                user = User.objects.get(id=user_id)
                                balance_obj = update_user_analysis_balance(user, subscription.plan)
                            else:
                                logger.warning(f"⚠️ Subscription {subscription.id} has no plan assigned")
                        except Exception as e:
                            logger.error(f"❌ Error updating analysis balance: {str(e)}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            
                    else:
                        logger.warning(f"⚠️ No subscription found for user {user_id}")
                        logger.warning(f"⚠️ Available subscriptions for user: {Subscription.objects.filter(user_id=user_id).count()}")
                        # Try to create or update subscription based on Stripe data
                        try:
                            user = User.objects.get(id=user_id)
                            plan_id = metadata.get('plan_id')
                            if plan_id:
                                plan = Plan.objects.get(id=plan_id)
                                
                                trial_end = None
                                current_period_end = None
                                
                                trial_end_timestamp = stripe_subscription.get('trial_end')
                                if trial_end_timestamp:
                                    trial_end = make_aware(
                                        datetime.datetime.fromtimestamp(trial_end_timestamp)
                                    )
                                
                                items = stripe_subscription.get('items', {})
                                if items and items.get('data'):
                                    first_item = items['data'][0]
                                    current_period_end_timestamp = first_item.get('current_period_end')
                                    if current_period_end_timestamp:
                                        current_period_end = make_aware(
                                            datetime.datetime.fromtimestamp(current_period_end_timestamp)
                                        )
                                
                                subscription = Subscription.objects.create(
                                    user=user,
                                    plan=plan,
                                    stripe_customer_id=obj.get('customer'),
                                    stripe_subscription_id=stripe_subscription.id,
                                    status=stripe_subscription.get('status', 'active'),
                                    trial_end=trial_end,
                                    current_period_end=current_period_end
                                )
                                
                                balance_obj = update_user_analysis_balance(user, plan)
                        except Exception as create_error:
                            logger.error(f"❌ Error creating subscription from webhook: {str(create_error)}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                        
                except Exception as e:
                    logger.error(f"❌ Error processing checkout.session.completed: {str(e)}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
            else:
                logger.warning(f"⚠️ Missing required data - user_id: {user_id}, subscription: {obj.get('subscription')}")

        elif event_type == "customer.subscription.created":
            
            try:
                # Safely handle timestamps
                trial_end = None
                current_period_end = None
                
                # Get trial_end from subscription level
                if obj.get("trial_end"):
                    trial_end = make_aware(
                        datetime.datetime.fromtimestamp(obj["trial_end"])
                    )
                
                # Get current_period_end from items
                items = obj.get("items", {})
                if items and items.get("data"):
                    first_item = items["data"][0]
                    if first_item.get("current_period_end"):
                        current_period_end = make_aware(
                            datetime.datetime.fromtimestamp(first_item["current_period_end"])
                        )
                
                subscription, created = Subscription.objects.update_or_create(
                    stripe_subscription_id=obj["id"],
                    defaults={
                        "status": obj["status"],
                        "trial_end": trial_end,
                        "current_period_end": current_period_end,
                    },
                )
                
                # Process referral benefits for subscription.created event
                try:
                    if subscription.user:
                        process_referral_benefits(subscription.user, subscription)
                except Exception as e:
                    logger.error(f"❌ Error in referral processing for subscription.created: {str(e)}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Update analysis balance
                try:
                    if subscription.user and subscription.plan:
                        balance_obj = update_user_analysis_balance(subscription.user, subscription.plan)
                    else:
                        logger.warning(f"⚠️ Cannot update balance - user: {subscription.user}, plan: {subscription.plan}")
                except Exception as e:
                    logger.error(f"❌ Error updating analysis balance: {str(e)}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                
            except Exception as e:
                logger.error(f"❌ Error processing customer.subscription.created: {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

        #  Handle subscription updated
        elif event_type == "customer.subscription.updated":
            
            try:
                # Get existing subscription to check for period change
                subscription = Subscription.objects.filter(
                    stripe_subscription_id=obj["id"]
                ).first()
                
                # Safely handle timestamps
                trial_end = None
                current_period_end = None
                
                if obj.get("trial_end"):
                    trial_end = make_aware(
                        datetime.datetime.fromtimestamp(obj["trial_end"])
                    )
                
                if obj.get("current_period_end"):
                    current_period_end = make_aware(
                        datetime.datetime.fromtimestamp(obj["current_period_end"])
                    )
                
                
                # Check if it's a new billing period (renewal)
                if subscription and subscription.current_period_end and current_period_end:
                    if current_period_end > subscription.current_period_end:
                        try:
                            if subscription.plan:
                                update_user_analysis_balance(subscription.user, subscription.plan)
                        except Exception as e:
                            logger.error(f"❌ Error resetting analysis balance: {str(e)}")
                
                updated_count = Subscription.objects.filter(
                    stripe_subscription_id=obj["id"]
                ).update(
                    status=obj["status"],
                    trial_end=trial_end,
                    current_period_end=current_period_end,
                )
                
            except Exception as e:
                logger.error(f"❌ Error processing customer.subscription.updated: {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

        # ✅ Handle subscription deleted/cancelled
        elif event_type == "customer.subscription.deleted":
            
            try:
                updated_count = Subscription.objects.filter(
                    stripe_subscription_id=obj["id"]
                ).update(status="canceled")
                
            except Exception as e:
                logger.error(f"❌ Error processing customer.subscription.deleted: {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        
        else:
            logger.info(f"ℹ️ Unhandled webhook event type: {event_type}")

    except Exception as e:
        logger.error(f"❌ Error processing webhook event {event_type}: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return HttpResponse(status=500)

    return HttpResponse(status=200)


class UserAnalysisBalanceView(APIView):
    """Get user's current analysis balance"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        try:
            balance_obj = analysesBalance.objects.get(user=request.user)
            is_unlimited = balance_obj.balance >= 999999
            
            return Response({
                "balance": balance_obj.balance if not is_unlimited else "unlimited",
                "is_unlimited": is_unlimited,
                "updated_at": balance_obj.updated_at
            }, status=200)
        except analysesBalance.DoesNotExist:
            return Response({
                "balance": 0,
                "is_unlimited": False,
                "message": "No active subscription"
            }, status=200)



class AutoRenewalView(APIView):

    def post(self, request):
        auto_renew = request.data.get("auto_renew")

        if auto_renew is None:
            return Response(
                {"error": "auto_renew field is required"},
                status=400
            )

        if isinstance(auto_renew, str):
            auto_renew = auto_renew.lower() == "true"

        try:
            subscription = Subscription.objects.get(
                user=request.user,
                status__in=["active", "trialing"]
            )
        except Subscription.DoesNotExist:
            return Response(
                {"error": "No active subscription found"},
                status=404
            )

        try:
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=not auto_renew
            )

            subscription.auto_renew = auto_renew
            subscription.save(update_fields=["auto_renew"])

            return Response({
                "message": "Auto-renewal updated successfully",
                "subscription_id": subscription.id,
                "auto_renew": subscription.auto_renew
            }, status=200)

        except stripe.error.StripeError as e:
            return Response(
                {"error": f"Stripe error: {str(e)}"},
                status=400
            )








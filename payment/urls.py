from django.urls import path #type:ignore

from payment.StripeSubscription import CreateSubscriptionView
from payment.StripeWebhook import StripeWebhookView
from payment.paypal_event_views import AnalysisCreditTransactionViews, PaypalEventViews, PlanDetailView, PlanViews # type: ignore
from .views import *
# from .onetimepayment import PurchaseOneTimeCreditsView
from .views import *

urlpatterns = [
      # path("create-subscription/", CreateSubscriptionView.as_view(), name="create-subscription"),
      # path("payment-success/", PaymentSuccessView.as_view(), name="payment-success"),
      # path("payment-cancel/", PaymentCancelView.as_view(), name="payment-cancel"),
      # path("checkout-status/", CheckoutSessionStatusView.as_view(), name="checkout-status"),
      # path("subscription-status/", UserSubscriptionStatusView.as_view(), name="subscription-status"),
      # path("webhook/", stripe_webhook, name="stripe-webhook"),
      # path("webhook-test/", WebhookTestView.as_view(), name="webhook-test"),
      # path("test-referral-benefits/", TestReferralBenefitsView.as_view(), name="test-referral-benefits"),
      # path("referral-status/", CheckReferralStatusView.as_view(), name="referral-status"),
      # path("analysis-balance/", UserAnalysisBalanceView.as_view(), name="analysis-balance"),
      
      # one-time purchase credits
      # path("purchase-credits/", PurchaseOneTimeCreditsView.as_view(), name="purchase-credits"),
      
      # Auto Renewal
      # path("auto-renewal/", AutoRenewalView.as_view(), name="auto-renewal"),
      
      # paypal response
      path("plans/", PlanViews.as_view(), name="plan-list-create"),
      path("plans/<int:id>/", PlanDetailView.as_view(), name="plan-update"),
      path("paypal-events/", PaypalEventViews.as_view(), name="paypal-events"),
      
      # AnalysisCreditTransaction
      path("analysis-credit-transactions/", AnalysisCreditTransactionViews.as_view(), name="analysis-credit-transactions"),
      
      # stripe
      path("stripe/plans/", PlanViews.as_view(), name="stripe-plan-list-create"),
      path("stripe/plans/<int:id>/", PlanDetailView.as_view(), name="stripe-plan-update"),
      
      # create subscription session
      path("stripe/create-subscription/", CreateSubscriptionView.as_view(), name="stripe-create-subscription"),
      # stripe webhook
      path("webhook/", StripeWebhookView.as_view(), name="stripe-webhook"),
]
from django.urls import path # type: ignore
from .views import *
from .onetimepayment import PurchaseOneTimeCreditsView

urlpatterns = [
      path("create-subscription/", CreateSubscriptionView.as_view(), name="create-subscription"),
      path("payment-success/", PaymentSuccessView.as_view(), name="payment-success"),
      path("payment-cancel/", PaymentCancelView.as_view(), name="payment-cancel"),
      path("checkout-status/", CheckoutSessionStatusView.as_view(), name="checkout-status"),
      path("subscription-status/", UserSubscriptionStatusView.as_view(), name="subscription-status"),
      path("webhook/", stripe_webhook, name="stripe-webhook"),
      path("webhook-test/", WebhookTestView.as_view(), name="webhook-test"),
      path("plans/", PlanListCreateView.as_view(), name="plan-list-create"),
      path("plans/<int:id>/", PlanUpdateView.as_view(), name="plan-update"),
      path("test-referral-benefits/", TestReferralBenefitsView.as_view(), name="test-referral-benefits"),
      path("referral-status/", CheckReferralStatusView.as_view(), name="referral-status"),
      path("analysis-balance/", UserAnalysisBalanceView.as_view(), name="analysis-balance"),
      
      # one-time purchase credits
      path("purchase-credits/", PurchaseOneTimeCreditsView.as_view(), name="purchase-credits"),
      
      # Auto Renewal
      path("auto-renewal/", AutoRenewalView.as_view(), name="auto-renewal"),
]
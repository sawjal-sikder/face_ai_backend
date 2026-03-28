from .models import StripePlan, Subscription, AnalysisCreditTransaction
from django.contrib import admin

@admin.register(StripePlan)
class StripePlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'interval', 'credits', 'active')
    list_filter = ('interval', 'active')
    search_fields = ('name',)
    
    
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'amount', 'stripe_customer_id', 'stripe_subscription_id')
    search_fields = ('user__email', 'plan__name', 'stripe_customer_id', 'stripe_subscription_id')
    list_filter = ('plan__name',)
    
@admin.register(AnalysisCreditTransaction)
class AnalysisCreditTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'credits', 'type', 'reason', 'created_at')
    search_fields = ('user__email', 'type', 'reason')
    list_filter = ('type', 'created_at')
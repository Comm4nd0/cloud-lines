from django.conf import settings as django_settings
from django.views.decorators.http import require_POST
from django.shortcuts import redirect

import stripe

from .currencies import get_countries
from .models import StripeAccount
from account.views import get_main_account
from cloudlines.constants import BoltonTypes


class StripeAccountManager:
    def __init__(self, request, attached_service):
        self.request = request
        self.attached_service = attached_service

        stripe.api_key = self.get_stripe_secret_key()
        self.stripe_account, created = StripeAccount.objects.get_or_create(account=self.attached_service)

    def get_stripe_secret_key(self):
        if self.request.META['HTTP_HOST'] in django_settings.TEST_STRIPE_DOMAINS:
            return django_settings.STRIPE_TEST_SECRET_KEY
        else:
            return django_settings.STRIPE_SECRET_KEY

    def get_stripe_public_key(self):
        if self.request.META['HTTP_HOST'] in django_settings.TEST_STRIPE_DOMAINS:
            return django_settings.STRIPE_TEST_PUBLIC_KEY
        else:
            return django_settings.STRIPE_PUBLIC_KEY
    
    def create_connect_account(self, business_type='individual', country='United Kingdom'):
        if not self.stripe_account.stripe_acct_id:
            # create initial account
            connect_account = stripe.Account.create(
                type='express',
                country=country,
                email=f"{self.request.user.email}",
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                business_type=business_type,
                company={
                    'name': self.request.META['HTTP_HOST'],
                    "directors_provided": True,
                    "executives_provided": True,
                },
            )
        self.stripe_account.stripe_acct_id = connect_account.id
        connect_account = self.get_account_link()

        # birth notification product
        if not self.stripe_account.bn_stripe_product_id:
            # create product
            product = stripe.Product.create(name=BoltonTypes.NAMES[BoltonTypes.BIRTH_NOTIFICATION],
                                            stripe_account=self.stripe_account.stripe_acct_id)
            self.stripe_account.bn_stripe_product_id = product.id
        # pedigree reg product
        ## TODO: Add logic for pedigree registration product

        self.stripe_account.save()

        return connect_account

    def get_account_edit_link(self):
        # Logic for creating an edit account link
        try:
            return stripe.Account.create_login_link(self.stripe_account.stripe_acct_id)
        except stripe.error.InvalidRequestError:
            if self.stripe_account.stripe_acct_id:
                return self.get_account_link()
            else:
                return None

    def manage_existing_stripe_account(self):
        # get stripe connect account details
        stripe_package = stripe.Account.retrieve(self.stripe_account.stripe_acct_id)
        return stripe_package
    
    def get_account_link(self):
        account_link = stripe.AccountLink.create(
            account=self.stripe_account.stripe_acct_id,
            refresh_url=f'{django_settings.HTTP_PROTOCOL}://{self.request.META["HTTP_HOST"]}',
            return_url=f'{django_settings.HTTP_PROTOCOL}://{self.request.META["HTTP_HOST"]}',
            type='account_onboarding',
        )
        return account_link

@require_POST
def setup_connect_account(request):
    attached_service = get_main_account(request.user)
    stripe_manager = StripeAccountManager(request, attached_service)
    # Extract form data
    country = request.POST.get('country')
    countries = get_countries()
    country_code = 'GB'
    for code, name in countries.items():
        if name.lower() == country.lower():
            country_code = code
            break
    business_type = request.POST.get('businessType')

    connect_account = stripe_manager.create_connect_account(business_type, country_code)

    # Redirect to the Stripe account onboarding flow
    print(connect_account)
    return redirect(connect_account.url)
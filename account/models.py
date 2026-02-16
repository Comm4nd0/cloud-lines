from django.db import models
from django.contrib.auth.models import User
from cloud_lines.models import Service
from cloud_lines.models import Bolton
from json import dumps
from cloudlines.constants import BoltonTypes, SiteModes


def user_directory_path(instance, filename):
    return 'acc_{0}_{1}/{2}'.format(instance.id, instance.domain.replace('https://', ''), filename)


class UserDetail(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, related_name='user')
    phone = models.CharField(max_length=15, blank=False)
    stripe_id = models.CharField(max_length=50, blank=True)
    current_service = models.ForeignKey('AttachedService', on_delete=models.SET_NULL, null=True, blank=True)
    graphs = models.TextField(default=dumps({
        'selected': [],
        'max_reached': False
    }), verbose_name="Dashboard Graphs")
    privacy_agreed = models.DateTimeField(null=True, blank=True)
    privacy_version = models.CharField(max_length=10, blank=True)
    data_protection_agreed = models.DateTimeField(null=True, blank=True)
    data_protection_version = models.CharField(max_length=10, blank=True)
    bn_stripe_id = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return str(self.user)


class AttachedBolton(models.Model):
    """
    1 == birth notifications
    2 == memberships
    """
    bolton = models.CharField(max_length=10)
    # session id
    stripe_payment_token = models.CharField(max_length=255, blank=True)
    stripe_sub_id = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=False)

    # used by BN package for storing their custom account id
    stripe_acct_id = models.CharField(max_length=255, blank=True)

    def bolton_name(self):
        return BoltonTypes.NAMES[self.bolton]

    def __str__(self):
        return self.bolton_name()


class AttachedService(models.Model):
    user = models.ForeignKey(UserDetail, on_delete=models.CASCADE, related_name='attached_service', null=True, blank=True)
    admin_users = models.ManyToManyField(User, related_name='admin_users', blank=True)
    contributors = models.ManyToManyField(User, related_name='contributors', blank=True)
    read_only_users = models.ManyToManyField(User, related_name='read_only_users', blank=True)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    boltons = models.ManyToManyField(AttachedBolton, related_name='boltons', blank=True)
    domain = models.CharField(max_length=250, blank=True)
    organisation_or_society_name = models.CharField(max_length=250, blank=True)
    image = models.ImageField(upload_to=user_directory_path, blank=True)
    animal_type = models.CharField(max_length=250)
    custom_fields = models.TextField(blank=True)
    pedigree_columns = models.CharField(blank=False, max_length=500, default="reg_no,mean_kinship,name,dob,status,breed,sex")
    mother_title = models.CharField(max_length=250, default='Mother')
    father_title = models.CharField(max_length=250, default='Father')
    coi_timeout = models.IntegerField(default=60)
    mean_kinship_timeout = models.IntegerField(default=60)
    metrics = models.BooleanField(default=False)
    pedigree_charging = models.BooleanField(default=False)
    pedigrees_visible = models.BooleanField(default=False) # can users see each others pedigrees

    SITE_MODES = SiteModes.CHOICES
    site_mode = models.CharField(max_length=13, choices=SITE_MODES, blank=True, null=True, default=SiteModes.POULTRY)

    INCREMENTS = (
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    )
    increment = models.CharField(max_length=10, choices=INCREMENTS, default=None, null=True, blank=True)
    active = models.BooleanField(default=False)
    subscription_id = models.CharField(max_length=250, blank=True)
    stripe_payment_token = models.CharField(max_length=250, blank=True)

    install_available = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.organisation_or_society_name}"


class StripeAccount(models.Model):
    # created under BN in error, this is used for all payments
    account = models.ForeignKey(AttachedService, on_delete=models.SET_NULL, blank=True, null=True,
                                verbose_name="BnN Stripe Account")
    attached_bolton = models.ForeignKey(AttachedBolton, on_delete=models.SET_NULL, blank=True, null=True,
                                        verbose_name="Attached Bolton")
    stripe_acct_id = models.CharField(max_length=255, blank=True, unique=True)

    account_name = models.CharField(max_length=255, blank=True)

    currency = models.CharField(max_length=255, default="GBP", blank=True)

    ## birth notifications
    bn_charging = models.BooleanField(default=False)
    # set to "Birth Notification"
    bn_stripe_product_id = models.CharField(max_length=255, blank=True, unique=False)
    # price of BN
    bn_cost_id = models.CharField(max_length=255, blank=True, unique=False)
    # Price of child
    bn_child_cost_id = models.CharField(max_length=255, blank=True, unique=False)
from django.db import models
from django.contrib.auth.models import User
from pedigree.models import Pedigree
from breeder.models import Breeder
from account.models import AttachedService, AttachedBolton, StripeAccount
from cloudlines.constants import BnChildStatus, PedigreeSex


class BnChild(models.Model):
    tag_no = models.CharField(max_length=100, blank=True, verbose_name='Tag Number', help_text="Must be unique")
    STATUSES = BnChildStatus.CHOICES

    status = models.CharField(max_length=12, choices=STATUSES, null=True, default='unknown',
                              help_text="Accepted formats: dead, alive, unknown", verbose_name="Status")

    GENDERS = (
        (PedigreeSex.MALE, 'Male'),
        (PedigreeSex.FEMALE, 'Female'),
    )

    sex = models.CharField(max_length=10, choices=GENDERS, null=True, default='unknown',
                           help_text="Accepted formats: male, female", verbose_name="Sex")

    comments = models.TextField(max_length=1000, blank=True, null=True, verbose_name="Comments",
                               help_text="Max 1000 characters")

    for_sale = models.BooleanField(null=True, default=False)

    pedigree = models.ForeignKey(Pedigree, related_name='registered_ped', on_delete=models.SET_NULL, blank=True, null=True)
    approved = models.BooleanField(default=False)


class BirthNotification(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Account")
    account = models.ForeignKey(AttachedService, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Account")
    attached_bolton = models.ForeignKey(AttachedBolton, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Attached Bolton")
    mother = models.ForeignKey(Pedigree, related_name='bnmother', on_delete=models.SET_NULL, blank=True, null=True)
    father = models.ForeignKey(Pedigree, related_name='bnfather', on_delete=models.SET_NULL, blank=True, null=True)

    births = models.ManyToManyField(BnChild, related_name='births', blank=True)

    bn_number = models.CharField(max_length=255, blank=True, unique=True)
    dob = models.DateField(blank=True, null=True, verbose_name="Date Of Birth(s)")
    date_added = models.DateTimeField(auto_now_add=True)
    comments = models.TextField(max_length=1000, blank=True, null=True, verbose_name="Comments", help_text="Max 1000 characters")
    breeder = models.ForeignKey(Breeder, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Breeder")

    # session id
    stripe_payment_token = models.CharField(max_length=255, blank=True)
    paid = models.BooleanField(default=False)

    complete = models.BooleanField(default=False)

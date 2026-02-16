from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from json import loads


class Service(models.Model):
    ordering = models.IntegerField()
    active = models.BooleanField(default=True)
    icon = models.CharField(max_length=500, blank=True)
    image = models.FileField(blank=True)
    service_name = models.CharField(max_length=50, unique=True)
    admin_users = models.IntegerField()
    contrib_users = models.IntegerField()
    read_only_users = models.IntegerField()
    number_of_animals = models.IntegerField()
    multi_breed = models.BooleanField()
    support = models.BooleanField()
    support_cost_per_year = models.DecimalField(max_digits=5, decimal_places=2)
    price_per_month = models.DecimalField(max_digits=5, decimal_places=2)
    price_per_year = models.DecimalField(max_digits=5, decimal_places=2)
    total_price_per_year = models.DecimalField(max_digits=6, decimal_places=2)
    service_description = models.TextField()

    service_id = models.CharField(max_length=100, blank=True)
    monthly_id = models.CharField(max_length=100, blank=True)
    yearly_id = models.CharField(max_length=100, blank=True)

    service_test_id = models.CharField(max_length=100, blank=True)
    monthly_test_id = models.CharField(max_length=100, blank=True)
    yearly_test_id = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.service_name

    class Meta:
        ordering = ['ordering']


class Gallery(models.Model):
    title = models.CharField(max_length=100, blank=True)
    image = models.ImageField(blank=True)
    detail = models.CharField(max_length=200, blank=True)


class Bolton(models.Model):
    name = models.CharField(max_length=50)
    price = models.FloatField()
    stripe_price_id = models.CharField(max_length=250, blank=True)
    test_stripe_price_id = models.CharField(max_length=250, blank=True)
    description = models.TextField()
    visible_to_public = models.BooleanField(default=True)

    def __str__(self):
        return str(self.name)


class Page(models.Model):
    title = models.CharField(max_length=50, unique=True,)
    sub_title = models.CharField(max_length=150, blank=True)
    body = models.TextField()
    image = models.ImageField(blank=True)

    def __str__(self):
        return self.title


class Faq(models.Model):
    question = models.CharField(max_length=250)
    answer = models.TextField()

    def __str__(self):
        return self.question


class Contact(models.Model):
    name = models.CharField(max_length=250)
    email = models.CharField(max_length=250)
    phone = models.CharField(max_length=50, blank=True)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, blank=True, null=True)
    subject = models.CharField(max_length=250)
    message = models.TextField()

    def __str__(self):
        return self.name


class Testimonial(models.Model):
    name = models.CharField(max_length=250)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, blank=True, null=True)
    body = models.TextField()

    def __str__(self):
        return str(self.name)


class LargeTierQueue(models.Model):
    from account.models import UserDetail, AttachedService
    from cloudlines.constants import BuildStates
    subdomain = models.CharField(max_length=255, blank=True, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, related_name='luser')
    user_detail = models.ForeignKey(UserDetail, on_delete=models.CASCADE, null=True, related_name='user_detail')
    attached_service = models.ForeignKey(AttachedService, on_delete=models.CASCADE, null=True, related_name='lattached_service')

    BUILD_STATE = BuildStates.CHOICES
    build_state = models.CharField(max_length=20, choices=BUILD_STATE, default=BuildStates.WAITING)
    build_status = models.CharField(max_length=255, blank=True)
    percentage_complete = models.IntegerField(default=0, null=True)

    def username(self):
        return self.user.username

    def service_id(self):
        return self.attached_service.service.pk

    def stripe_id(self):
        return self.user_detail.stripe_id

    def site_mode(self):
        return self.attached_service.site_mode

    def animal_type(self):
        return self.attached_service.animal_type

    def user_data(self):
        from django.core import serializers
        return loads(serializers.serialize("json", [self.user]))

    def services_data(self):
        from django.core import serializers
        return loads(serializers.serialize("json", Service.objects.all()))

    def __str__(self):
        return str(self.subdomain)


class Blog(models.Model):
    date_added = models.DateTimeField(default=timezone.now)
    image = models.FileField(blank=True, null=True)
    video = models.CharField(max_length=250, blank=True, null=True)
    title = models.CharField(max_length=250)
    content = models.TextField()

    def __str__(self):
        return str(self.title)

    class Meta:
        ordering = ['-date_added']


class Update(models.Model):
    date = models.DateField(auto_now_add=False)
    body = models.TextField(default="""<strong>Features</strong>
    <br>
        <ul class="list-icons">
            <li><i class="fad fa-check text-info"></i> </li>
        </ul>
<strong>Bug Fixes</strong>
        <ul class="list-icons">
            <li><i class="fad fa-check text-info"></i> </li>
        </ul>""")

    def __str__(self):
        return str(self.date)

    class Meta:
        ordering = ['date']
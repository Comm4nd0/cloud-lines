from django.db import models
from django.contrib.auth.models import User
from breeder.models import Breeder
from breed.models import Breed
from account.models import AttachedService
from django.core.validators import MaxValueValidator, MinValueValidator
from cloudlines.constants import States, PedigreeStatus, PedigreeSex


class Pedigree(models.Model):
    class Meta:
        ordering = ['-reg_no']

    STATES = States.CHOICES
    state = models.CharField(max_length=10, choices=STATES, null=True, default=States.APPROVED, verbose_name="State")
    creator = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Creator")
    account = models.ForeignKey(AttachedService, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Account")
    breeder = models.ForeignKey(Breeder, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Breeder", help_text="Often the same as Current Owner")
    current_owner = models.ForeignKey(Breeder, on_delete=models.SET_NULL, blank=True, null=True, related_name='owner', verbose_name='Current Owner', help_text="Often the same as Breeder")
    reg_no = models.CharField(max_length=100, blank=True, unique=True, verbose_name='Registration Number', help_text="Must be unique")
    tag_no = models.CharField(max_length=100, blank=True, null=True, verbose_name='Tag Number')
    name = models.CharField(max_length=100, blank=True, verbose_name="Name")
    description = models.TextField(max_length=1000, blank=True, null=True, verbose_name="Description", help_text="Max 1000 characters")
    date_of_registration = models.DateField(blank=True, null=True, verbose_name='Date of Registration', help_text="Date formats: 1984/09/31, 84/09/31, 31/09/1984, 31/09/84, 1984-09-31, 84-09-31, 31-09-1984, 31-09-84")
    dob = models.DateField(blank=True, null=True, verbose_name='Date of Birth', help_text="Date formats: 1984/09/31, 84/09/31, 31/09/1984, 31/09/84, 1984-09-31, 84-09-31, 31-09-1984, 31-09-84")
    dod = models.DateField(blank=True, null=True, verbose_name='Date of Death', help_text="Date formats: 1984/09/31, 84/09/31, 31/09/1984, 31/09/84, 1984-09-31, 84-09-31, 31-09-1984, 31-09-84")

    STATUSES = PedigreeStatus.CHOICES

    status = models.CharField(max_length=10, choices=STATUSES, null=True, default=PedigreeStatus.UNKNOWN,
                           help_text="Accepted formats: dead, alive, unknown", verbose_name="Status")

    GENDERS = PedigreeSex.CHOICES

    sex = models.CharField(max_length=10, choices=GENDERS, null=True, default=PedigreeSex.UNKNOWN,
                            help_text="Accepted formats: male, female, castrated, unknown", verbose_name="Sex")

    litter_size = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(50)], default=1,
                            help_text="Accepted range: 1-50", verbose_name="Litter Size")

    parent_father = models.ForeignKey('self', related_name='father', on_delete=models.SET_NULL, blank=True, null=True, verbose_name='Father', help_text="This should be the parents registration number.")
    parent_father_notes = models.CharField(max_length=500, blank=True, null=True, verbose_name='Father Notes', help_text="Max 500 characters")
    parent_mother = models.ForeignKey('self', related_name='mother', on_delete=models.SET_NULL, blank=True, null=True, verbose_name='Mother', help_text="This should be the parents registration number.")
    parent_mother_notes = models.CharField(max_length=500, blank=True, null=True, verbose_name='Mother Notes', help_text="Max 500 characters")
    breed_group = models.CharField(max_length=255, blank=True, null=True, verbose_name='Breed Group')
    breed = models.ForeignKey(Breed, on_delete=models.CASCADE, blank=True, null=True, related_name='Breed', verbose_name="Breed")
    coi = models.DecimalField(decimal_places=4, max_digits=5, default=0, blank=True, verbose_name="COI")
    mean_kinship = models.DecimalField(decimal_places=4, max_digits=5, default=0, blank=True, verbose_name="Mean Kinship")
    # hidden
    date_added = models.DateTimeField(auto_now_add=True, verbose_name="Date Added")
    custom_fields = models.TextField(blank=True, verbose_name="Custom Fields")
    sale_or_hire = models.BooleanField(default=False, help_text="Is the pedigree for sale/hire, or not?", verbose_name="For Sale/Hire")
    paid = models.BooleanField(default=False)
    stripe_payment_token = models.CharField(max_length=255, blank=True, null=True)

    def parent_father_reg_no(self):
        if self.parent_father:
            return self.parent_father.reg_no

    def parent_father_name(self):
        if self.parent_father:
            return self.parent_father.name

    def parent_mother_reg_no(self):
        if self.parent_mother:
            return self.parent_mother.reg_no

    def parent_mother_name(self):
        if self.parent_mother:
            return self.parent_mother.name

    def breeder_breeding_prefix(self):
        if self.breeder:
            return self.breeder.breeding_prefix

    def current_owner_breeding_prefix(self):
        if self.current_owner:
            return self.current_owner.breeding_prefix

    def breed_breed_name(self):
        if self.breed:
            return self.breed.breed_name

    def __str__(self):
        return self.reg_no


def user_directory_path(instance, filename):
    return 'acc_{0}_{1}/{2}'.format(instance.account.id, instance.account.domain.replace('https://', ''), filename)


class PedigreeImage(models.Model):
    STATES = States.CHOICES
    state = models.CharField(max_length=10, choices=STATES, null=True, default=States.APPROVED)
    reg_no = models.ForeignKey(Pedigree, related_name='images', on_delete=models.SET_NULL, blank=True, null=True)
    account = models.ForeignKey(AttachedService, on_delete=models.SET_NULL, blank=True, null=True)
    image = models.ImageField(upload_to=user_directory_path)
    title = models.CharField(max_length=100, blank=True)
    description = models.TextField(max_length=500, blank=True)

    def __str__(self):
        return str(self.reg_no)
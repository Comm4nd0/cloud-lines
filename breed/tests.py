from django.test import TestCase
from django.contrib.auth.models import User
from breed.models import Breed
from account.models import AttachedService, UserDetail
from cloud_lines.models import Service


class BreedModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            ordering=1,
            service_name='Breed Test Service',
            admin_users=5,
            contrib_users=5,
            read_only_users=5,
            number_of_animals=100,
            multi_breed=True,
            support=True,
            support_cost_per_year=0,
            price_per_month=10,
            price_per_year=100,
            total_price_per_year=100,
            service_description='Test',
        )
        cls.user = User.objects.create_user(username='breeduser', password='testpass123')
        cls.user_detail = UserDetail.objects.create(user=cls.user, phone='1234567890')
        cls.account = AttachedService.objects.create(
            user=cls.user_detail,
            service=cls.service,
            domain='https://breedtest.cloud-lines.com',
            animal_type='poultry',
            active=True,
        )
        cls.breed = Breed.objects.create(
            account=cls.account,
            breed_name='Rhode Island Red',
            breed_description='A popular breed.',
        )

    def test_str_returns_breed_name(self):
        self.assertEqual(str(self.breed), 'Rhode Island Red')

    def test_default_mk_threshold_is_zero(self):
        self.assertEqual(self.breed.mk_threshold, 0)

    def test_custom_mk_threshold(self):
        breed = Breed.objects.create(
            account=self.account,
            breed_name='Custom MK Breed',
            mk_threshold=0.1234,
        )
        self.assertEqual(float(breed.mk_threshold), 0.1234)

    def test_breed_admins_m2m(self):
        admin = User.objects.create_user(username='breadadmin', password='pass')
        self.breed.breed_admins.add(admin)
        self.assertIn(admin, self.breed.breed_admins.all())

    def test_breed_admins_empty_by_default(self):
        breed = Breed.objects.create(account=self.account, breed_name='No Admins Breed')
        self.assertEqual(breed.breed_admins.count(), 0)

    def test_custom_fields_blank_by_default(self):
        self.assertEqual(self.breed.custom_fields, '')

    def test_date_added_auto(self):
        self.assertIsNotNone(self.breed.date_added)

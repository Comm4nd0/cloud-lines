from django.test import TestCase
from django.contrib.auth.models import User
from breeder.models import Breeder
from account.models import AttachedService, UserDetail
from cloud_lines.models import Service


class BreederModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            ordering=1,
            service_name='Breeder Test Service',
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
        cls.user = User.objects.create_user(username='breederuser', password='testpass123')
        cls.user_detail = UserDetail.objects.create(user=cls.user, phone='1234567890')
        cls.account = AttachedService.objects.create(
            user=cls.user_detail,
            service=cls.service,
            domain='https://breedertest.cloud-lines.com',
            animal_type='poultry',
            active=True,
        )
        cls.breeder = Breeder.objects.create(
            account=cls.account,
            breeding_prefix='JD',
            contact_name='John Doe',
            address_line_1='123 Farm Lane',
            town='Farmville',
            country='UK',
            postcode='FA1 2RM',
            email='john@farm.com',
            phone_number1='01onal234567',
            user=cls.user,
        )

    def test_str_returns_breeding_prefix(self):
        self.assertEqual(str(self.breeder), 'JD')

    def test_data_visible_default_false(self):
        self.assertFalse(self.breeder.data_visible)

    def test_active_default_false(self):
        self.assertFalse(self.breeder.active)

    def test_custom_fields_blank_by_default(self):
        self.assertEqual(self.breeder.custom_fields, '')

    def test_breeder_with_user_relation(self):
        self.assertEqual(self.breeder.user, self.user)

    def test_set_null_on_account_delete(self):
        service2 = Service.objects.create(
            ordering=2,
            service_name='Temp Breeder Service',
            admin_users=1, contrib_users=1, read_only_users=1,
            number_of_animals=10, multi_breed=False, support=False,
            support_cost_per_year=0, price_per_month=5,
            price_per_year=50, total_price_per_year=50,
            service_description='Temp',
        )
        user2 = User.objects.create_user(username='tempbreeder', password='pass')
        ud2 = UserDetail.objects.create(user=user2, phone='000')
        account2 = AttachedService.objects.create(
            user=ud2, service=service2,
            domain='https://temp.cloud-lines.com', animal_type='poultry', active=True,
        )
        breeder = Breeder.objects.create(account=account2, breeding_prefix='TEMP')
        account2.delete()
        breeder.refresh_from_db()
        self.assertIsNone(breeder.account)

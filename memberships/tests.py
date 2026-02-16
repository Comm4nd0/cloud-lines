from django.test import TestCase
from django.contrib.auth.models import User
from memberships.models import Membership
from account.models import AttachedService, UserDetail
from cloud_lines.models import Service


class MembershipModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            ordering=1,
            service_name='Membership Test Service',
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
        cls.user = User.objects.create_user(username='memuser', password='testpass123')
        cls.user_detail = UserDetail.objects.create(user=cls.user, phone='1234567890')
        cls.account = AttachedService.objects.create(
            user=cls.user_detail,
            service=cls.service,
            domain='https://memtest.cloud-lines.com',
            animal_type='poultry',
            active=True,
        )

    def test_create_new_token(self):
        membership = Membership.objects.create(account=self.account)
        token = membership.create_new_token()
        self.assertEqual(len(token), 32)
        self.assertEqual(membership.token, token)

    def test_get_or_create_token_creates_when_empty(self):
        membership = Membership.objects.create(account=self.account, token='')
        token = membership.get_or_create_token()
        self.assertEqual(len(token), 32)

    def test_get_or_create_token_returns_existing(self):
        membership = Membership.objects.create(account=self.account, token='existing_token_12345678901234567')
        token = membership.get_or_create_token()
        self.assertEqual(token, 'existing_token_12345678901234567')

    def test_token_persists_after_create(self):
        membership = Membership.objects.create(account=self.account)
        membership.create_new_token()
        membership.refresh_from_db()
        self.assertEqual(len(membership.token), 32)

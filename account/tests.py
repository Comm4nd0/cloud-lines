from django.test import TestCase
from django.contrib.auth.models import User
from account.models import UserDetail, AttachedService, AttachedBolton, StripeAccount
from cloud_lines.models import Service


class UserDetailModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='uduser', password='testpass123')
        cls.user_detail = UserDetail.objects.create(user=cls.user, phone='07712345678')

    def test_str_returns_username(self):
        self.assertEqual(str(self.user_detail), 'uduser')

    def test_default_graphs(self):
        import json
        graphs = json.loads(self.user_detail.graphs)
        self.assertEqual(graphs['selected'], [])
        self.assertFalse(graphs['max_reached'])

    def test_privacy_fields_null_by_default(self):
        self.assertIsNone(self.user_detail.privacy_agreed)
        self.assertEqual(self.user_detail.privacy_version, '')


class AttachedBoltonModelTest(TestCase):
    def test_bolton_name_birth_notification(self):
        bolton = AttachedBolton.objects.create(bolton='1')
        self.assertEqual(bolton.bolton_name(), 'Birth Notification')

    def test_bolton_name_memberships(self):
        bolton = AttachedBolton.objects.create(bolton='2')
        self.assertEqual(bolton.bolton_name(), 'Memberships')

    def test_str_returns_bolton_name(self):
        bolton = AttachedBolton.objects.create(bolton='1')
        self.assertEqual(str(bolton), 'Birth Notification')

    def test_active_default_false(self):
        bolton = AttachedBolton.objects.create(bolton='1')
        self.assertFalse(bolton.active)


class AttachedServiceModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            ordering=1,
            service_name='AS Test Service',
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
        cls.user = User.objects.create_user(username='asuser', password='testpass123')
        cls.user_detail = UserDetail.objects.create(user=cls.user, phone='1234567890')
        cls.account = AttachedService.objects.create(
            user=cls.user_detail,
            service=cls.service,
            domain='https://astest.cloud-lines.com',
            organisation_or_society_name='Test Society',
            animal_type='poultry',
            active=True,
        )

    def test_str_returns_organisation_name(self):
        self.assertEqual(str(self.account), 'Test Society')

    def test_default_site_mode_is_poultry(self):
        self.assertEqual(self.account.site_mode, 'poultry')

    def test_default_mother_title(self):
        self.assertEqual(self.account.mother_title, 'Mother')

    def test_default_father_title(self):
        self.assertEqual(self.account.father_title, 'Father')

    def test_default_coi_timeout(self):
        self.assertEqual(self.account.coi_timeout, 60)

    def test_default_mean_kinship_timeout(self):
        self.assertEqual(self.account.mean_kinship_timeout, 60)

    def test_metrics_default_false(self):
        self.assertFalse(self.account.metrics)

    def test_pedigree_charging_default_false(self):
        self.assertFalse(self.account.pedigree_charging)

    def test_pedigrees_visible_default_false(self):
        self.assertFalse(self.account.pedigrees_visible)

    def test_default_pedigree_columns(self):
        self.assertEqual(
            self.account.pedigree_columns,
            'reg_no,mean_kinship,name,dob,status,breed,sex'
        )

    def test_admin_users_m2m(self):
        admin = User.objects.create_user(username='admin1', password='pass')
        self.account.admin_users.add(admin)
        self.assertIn(admin, self.account.admin_users.all())

    def test_contributors_m2m(self):
        contrib = User.objects.create_user(username='contrib1', password='pass')
        self.account.contributors.add(contrib)
        self.assertIn(contrib, self.account.contributors.all())

    def test_read_only_users_m2m(self):
        ro = User.objects.create_user(username='readonly1', password='pass')
        self.account.read_only_users.add(ro)
        self.assertIn(ro, self.account.read_only_users.all())

    def test_boltons_m2m(self):
        bolton = AttachedBolton.objects.create(bolton='1')
        self.account.boltons.add(bolton)
        self.assertIn(bolton, self.account.boltons.all())

    def test_active_default_false(self):
        user2 = User.objects.create_user(username='inactive', password='pass')
        ud2 = UserDetail.objects.create(user=user2, phone='000')
        account = AttachedService.objects.create(
            user=ud2, animal_type='mammal',
        )
        self.assertFalse(account.active)

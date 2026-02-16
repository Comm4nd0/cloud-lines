from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.authtoken.models import Token
from pedigree.models import Pedigree
from breed.models import Breed
from breeder.models import Breeder
from breed_group.models import BreedGroup
from account.models import AttachedService, UserDetail
from cloud_lines.models import Service, Faq, Bolton, Update
from metrics.models import KinshipQueue, DataValidatorQueue, StudAdvisorQueue
from birth_notifications.models import BirthNotification, BnChild
from memberships.models import Membership
from datetime import date


def create_test_account(username, service_name, domain):
    """Helper to create a full user + account setup for testing."""
    service = Service.objects.create(
        ordering=1,
        service_name=service_name,
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
    user = User.objects.create_user(username=username, password='testpass123')
    user_detail = UserDetail.objects.create(user=user, phone='1234567890')
    account = AttachedService.objects.create(
        user=user_detail,
        service=service,
        domain=domain,
        animal_type='poultry',
        active=True,
    )
    user_detail.current_service = account
    user_detail.save()
    token = Token.objects.create(user=user)
    return user, user_detail, account, token


class AuthenticationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.user_detail, self.account, self.token = create_test_account(
            'authuser', 'Auth Service', 'https://auth.cloud-lines.com'
        )

    def test_unauthenticated_access_denied(self):
        response = self.client.get('/api/pedigrees/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ])

    def test_token_auth_works(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.get('/api/pedigrees/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_session_auth_works(self):
        self.client.login(username='authuser', password='testpass123')
        response = self.client.get('/api/pedigrees/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class PublicEndpointsTest(TestCase):
    """Test that public endpoints are accessible without auth and are read-only."""

    def setUp(self):
        self.client = APIClient()

    def test_services_list_accessible(self):
        Service.objects.create(
            ordering=1, service_name='Public Service', admin_users=1,
            contrib_users=1, read_only_users=1, number_of_animals=10,
            multi_breed=False, support=False, support_cost_per_year=0,
            price_per_month=5, price_per_year=50, total_price_per_year=50,
            service_description='Public',
        )
        response = self.client.get('/api/services/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_faq_list_accessible(self):
        Faq.objects.create(question='Test?', answer='Yes')
        response = self.client.get('/api/faq/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_bolton_list_accessible(self):
        Bolton.objects.create(name='Test Bolton', price=9.99, description='Test')
        response = self.client.get('/api/bolton/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_services_read_only_no_create(self):
        response = self.client.post('/api/services/', {
            'service_name': 'Hack Service', 'price_per_month': 0,
        })
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        ])

    def test_faq_read_only_no_create(self):
        response = self.client.post('/api/faq/', {'question': 'Hack?', 'answer': 'No'})
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        ])

    def test_bolton_read_only_no_create(self):
        response = self.client.post('/api/bolton/', {'name': 'Hack', 'price': 0})
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        ])


class PedigreeAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1, self.ud1, self.account1, self.token1 = create_test_account(
            'peduser1', 'Ped Service 1', 'https://ped1.cloud-lines.com'
        )
        self.user2, self.ud2, self.account2, self.token2 = create_test_account(
            'peduser2', 'Ped Service 2', 'https://ped2.cloud-lines.com'
        )
        self.breed1 = Breed.objects.create(account=self.account1, breed_name='Breed A')
        self.breed2 = Breed.objects.create(account=self.account2, breed_name='Breed B')
        self.ped1 = Pedigree.objects.create(
            reg_no='API-PED-001', account=self.account1, breed=self.breed1, name='Animal 1',
        )
        self.ped2 = Pedigree.objects.create(
            reg_no='API-PED-002', account=self.account2, breed=self.breed2, name='Animal 2',
        )

    def test_user_sees_only_own_pedigrees(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token1.key}')
        response = self.client.get('/api/pedigrees/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg_nos = [p['reg_no'] for p in response.data['results']]
        self.assertIn('API-PED-001', reg_nos)
        self.assertNotIn('API-PED-002', reg_nos)

    def test_user2_sees_only_own_pedigrees(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token2.key}')
        response = self.client.get('/api/pedigrees/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg_nos = [p['reg_no'] for p in response.data['results']]
        self.assertIn('API-PED-002', reg_nos)
        self.assertNotIn('API-PED-001', reg_nos)


class BreederAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1, self.ud1, self.account1, self.token1 = create_test_account(
            'brdruser1', 'Brdr Service 1', 'https://brdr1.cloud-lines.com'
        )
        self.user2, self.ud2, self.account2, self.token2 = create_test_account(
            'brdruser2', 'Brdr Service 2', 'https://brdr2.cloud-lines.com'
        )
        self.breeder1 = Breeder.objects.create(account=self.account1, breeding_prefix='B1')
        self.breeder2 = Breeder.objects.create(account=self.account2, breeding_prefix='B2')

    def test_user_sees_only_own_breeders(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token1.key}')
        response = self.client.get('/api/breeders/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        prefixes = [b['breeding_prefix'] for b in response.data['results']]
        self.assertIn('B1', prefixes)
        self.assertNotIn('B2', prefixes)


class KinshipAPIIsolationTest(TestCase):
    """Test that kinship/metrics endpoints properly filter by account."""

    def setUp(self):
        self.client = APIClient()
        self.user1, self.ud1, self.account1, self.token1 = create_test_account(
            'kinuser1', 'Kin Service 1', 'https://kin1.cloud-lines.com'
        )
        self.user2, self.ud2, self.account2, self.token2 = create_test_account(
            'kinuser2', 'Kin Service 2', 'https://kin2.cloud-lines.com'
        )
        self.kq1 = KinshipQueue.objects.create(
            account=self.account1, user=self.user1, file='test1.csv',
        )
        self.kq2 = KinshipQueue.objects.create(
            account=self.account2, user=self.user2, file='test2.csv',
        )

    def test_user_sees_only_own_kinship_queue(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token1.key}')
        response = self.client.get('/api/kinship/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [k['id'] for k in response.data['results']]
        self.assertIn(self.kq1.id, ids)
        self.assertNotIn(self.kq2.id, ids)

    def test_user2_cannot_see_user1_kinship(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token2.key}')
        response = self.client.get('/api/kinship/')
        ids = [k['id'] for k in response.data['results']]
        self.assertNotIn(self.kq1.id, ids)
        self.assertIn(self.kq2.id, ids)


class DataValidatorAPIIsolationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1, self.ud1, self.account1, self.token1 = create_test_account(
            'dvuser1', 'DV Service 1', 'https://dv1.cloud-lines.com'
        )
        self.user2, self.ud2, self.account2, self.token2 = create_test_account(
            'dvuser2', 'DV Service 2', 'https://dv2.cloud-lines.com'
        )
        self.dv1 = DataValidatorQueue.objects.create(
            account=self.account1, user=self.user1,
        )
        self.dv2 = DataValidatorQueue.objects.create(
            account=self.account2, user=self.user2,
        )

    def test_user_sees_only_own_data_validator(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token1.key}')
        response = self.client.get('/api/data_validation/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [d['id'] for d in response.data['results']]
        self.assertIn(self.dv1.id, ids)
        self.assertNotIn(self.dv2.id, ids)


class StudAdvisorAPIIsolationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1, self.ud1, self.account1, self.token1 = create_test_account(
            'sauser1', 'SA Service 1', 'https://sa1.cloud-lines.com'
        )
        self.user2, self.ud2, self.account2, self.token2 = create_test_account(
            'sauser2', 'SA Service 2', 'https://sa2.cloud-lines.com'
        )
        self.sa1 = StudAdvisorQueue.objects.create(
            account=self.account1, user=self.user1, file='sa1.csv', failed_message='',
        )
        self.sa2 = StudAdvisorQueue.objects.create(
            account=self.account2, user=self.user2, file='sa2.csv', failed_message='',
        )

    def test_user_sees_only_own_stud_advisor(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token1.key}')
        response = self.client.get('/api/stud_advisor/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [s['id'] for s in response.data['results']]
        self.assertIn(self.sa1.id, ids)
        self.assertNotIn(self.sa2.id, ids)


class BirthNotificationAPIIsolationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1, self.ud1, self.account1, self.token1 = create_test_account(
            'bnuser1', 'BN Service 1', 'https://bn1.cloud-lines.com'
        )
        self.user2, self.ud2, self.account2, self.token2 = create_test_account(
            'bnuser2', 'BN Service 2', 'https://bn2.cloud-lines.com'
        )
        self.bn1 = BirthNotification.objects.create(
            account=self.account1, user=self.user1, bn_number='BN-001',
        )
        self.bn2 = BirthNotification.objects.create(
            account=self.account2, user=self.user2, bn_number='BN-002',
        )

    def test_user_sees_only_own_birth_notifications(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token1.key}')
        response = self.client.get('/api/birth_notification/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bn_numbers = [bn['bn_number'] for bn in response.data['results']]
        self.assertIn('BN-001', bn_numbers)
        self.assertNotIn('BN-002', bn_numbers)


class LargeTierQueuePermissionTest(TestCase):
    """Test that large tier queue is admin-only."""

    def setUp(self):
        self.client = APIClient()
        self.user, self.ud, self.account, self.token = create_test_account(
            'ltuser', 'LT Service', 'https://lt.cloud-lines.com'
        )

    def test_non_admin_cannot_access_large_tier_queue(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.get('/api/large-tier-queue/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_large_tier_queue(self):
        self.user.is_staff = True
        self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.get('/api/large-tier-queue/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class CustomAuthTokenTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='tokenuser', password='testpass123', email='token@test.com'
        )

    def test_obtain_token(self):
        response = self.client.post('/api/api-token-auth', {
            'username': 'tokenuser',
            'password': 'testpass123',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertEqual(response.data['email'], 'token@test.com')

    def test_obtain_token_bad_credentials(self):
        response = self.client.post('/api/api-token-auth', {
            'username': 'tokenuser',
            'password': 'wrongpassword',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class MembershipAddEditUserTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.ud, self.account, self.token = create_test_account(
            'memowner', 'Mem Service', 'https://mem.cloud-lines.com'
        )
        self.membership = Membership.objects.create(account=self.account)
        self.membership.create_new_token()

    def test_invalid_token_denied(self):
        response = self.client.post('/api/membership-add-edit-user', {
            'token': 'invalid_token',
            'email': 'new@test.com',
            'username': 'newuser',
            'first_name': 'New',
            'last_name': 'User',
            'phone': '1234567890',
            'permission_level': 'read_only_users',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_valid_token_creates_user(self):
        response = self.client.post('/api/membership-add-edit-user', {
            'token': self.membership.token,
            'email': 'newmem@test.com',
            'username': 'newmemuser',
            'first_name': 'New',
            'last_name': 'Member',
            'phone': '9876543210',
            'permission_level': 'read_only_users',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['error'])
        self.assertTrue(User.objects.filter(email='newmem@test.com').exists())
        new_user = User.objects.get(email='newmem@test.com')
        self.assertIn(new_user, self.account.read_only_users.all())

    def test_invalid_permission_level(self):
        response = self.client.post('/api/membership-add-edit-user', {
            'token': self.membership.token,
            'email': 'badperm@test.com',
            'username': 'badpermuser',
            'first_name': 'Bad',
            'last_name': 'Perm',
            'phone': '1111111111',
            'permission_level': 'superadmin',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['error'])

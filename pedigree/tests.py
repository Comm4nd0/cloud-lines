from django.test import TestCase
from django.contrib.auth.models import User
from pedigree.models import Pedigree, PedigreeImage
from breed.models import Breed
from breeder.models import Breeder
from account.models import AttachedService, UserDetail
from cloud_lines.models import Service


class PedigreeModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            ordering=1,
            service_name='Test Service',
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
        cls.user = User.objects.create_user(username='testuser', password='testpass123')
        cls.user_detail = UserDetail.objects.create(user=cls.user, phone='1234567890')
        cls.account = AttachedService.objects.create(
            user=cls.user_detail,
            service=cls.service,
            domain='https://test.cloud-lines.com',
            animal_type='poultry',
            active=True,
        )
        cls.breed = Breed.objects.create(
            account=cls.account,
            breed_name='Test Breed',
        )
        cls.breeder = Breeder.objects.create(
            account=cls.account,
            breeding_prefix='TB',
            contact_name='Test Breeder',
        )
        cls.father = Pedigree.objects.create(
            reg_no='FATHER-001',
            name='Father',
            account=cls.account,
            breed=cls.breed,
            sex='male',
            status='alive',
        )
        cls.mother = Pedigree.objects.create(
            reg_no='MOTHER-001',
            name='Mother',
            account=cls.account,
            breed=cls.breed,
            sex='female',
            status='alive',
        )
        cls.pedigree = Pedigree.objects.create(
            reg_no='PED-001',
            name='Test Animal',
            account=cls.account,
            breed=cls.breed,
            breeder=cls.breeder,
            current_owner=cls.breeder,
            parent_father=cls.father,
            parent_mother=cls.mother,
            sex='male',
            status='alive',
            state='approved',
            creator=cls.user,
        )

    def test_str_returns_reg_no(self):
        self.assertEqual(str(self.pedigree), 'PED-001')

    def test_default_state_is_approved(self):
        p = Pedigree.objects.create(reg_no='PED-DEFAULT', account=self.account)
        self.assertEqual(p.state, 'approved')

    def test_default_status_is_unknown(self):
        p = Pedigree.objects.create(reg_no='PED-STATUS', account=self.account)
        self.assertEqual(p.status, 'unknown')

    def test_default_sex_is_unknown(self):
        p = Pedigree.objects.create(reg_no='PED-SEX', account=self.account)
        self.assertEqual(p.sex, 'unknown')

    def test_default_litter_size_is_one(self):
        p = Pedigree.objects.create(reg_no='PED-LITTER', account=self.account)
        self.assertEqual(p.litter_size, 1)

    def test_default_coi_is_zero(self):
        p = Pedigree.objects.create(reg_no='PED-COI', account=self.account)
        self.assertEqual(p.coi, 0)

    def test_default_mean_kinship_is_zero(self):
        p = Pedigree.objects.create(reg_no='PED-MK', account=self.account)
        self.assertEqual(p.mean_kinship, 0)

    def test_reg_no_is_unique(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Pedigree.objects.create(reg_no='PED-001', account=self.account)

    def test_parent_father_reg_no(self):
        self.assertEqual(self.pedigree.parent_father_reg_no(), 'FATHER-001')

    def test_parent_father_reg_no_none(self):
        p = Pedigree.objects.create(reg_no='PED-NOFATH', account=self.account)
        self.assertIsNone(p.parent_father_reg_no())

    def test_parent_father_name(self):
        self.assertEqual(self.pedigree.parent_father_name(), 'Father')

    def test_parent_mother_reg_no(self):
        self.assertEqual(self.pedigree.parent_mother_reg_no(), 'MOTHER-001')

    def test_parent_mother_name(self):
        self.assertEqual(self.pedigree.parent_mother_name(), 'Mother')

    def test_parent_mother_reg_no_none(self):
        p = Pedigree.objects.create(reg_no='PED-NOMOTH', account=self.account)
        self.assertIsNone(p.parent_mother_reg_no())

    def test_breeder_breeding_prefix(self):
        self.assertEqual(self.pedigree.breeder_breeding_prefix(), 'TB')

    def test_breeder_breeding_prefix_none(self):
        p = Pedigree.objects.create(reg_no='PED-NOBREED', account=self.account)
        self.assertIsNone(p.breeder_breeding_prefix())

    def test_current_owner_breeding_prefix(self):
        self.assertEqual(self.pedigree.current_owner_breeding_prefix(), 'TB')

    def test_breed_breed_name(self):
        self.assertEqual(self.pedigree.breed_breed_name(), 'Test Breed')

    def test_breed_breed_name_none(self):
        p = Pedigree.objects.create(reg_no='PED-NOBREEDNAME', account=self.account)
        self.assertIsNone(p.breed_breed_name())

    def test_ordering_is_by_reg_no_desc(self):
        pedigrees = list(Pedigree.objects.values_list('reg_no', flat=True)[:3])
        self.assertEqual(pedigrees, sorted(pedigrees, reverse=True))

    def test_self_referential_father_relationship(self):
        children = Pedigree.objects.filter(parent_father=self.father)
        self.assertIn(self.pedigree, children)

    def test_self_referential_mother_relationship(self):
        children = Pedigree.objects.filter(parent_mother=self.mother)
        self.assertIn(self.pedigree, children)

    def test_cascade_on_breed_delete(self):
        breed = Breed.objects.create(account=self.account, breed_name='Temp Breed')
        p = Pedigree.objects.create(reg_no='PED-CASCADE', account=self.account, breed=breed)
        breed.delete()
        self.assertFalse(Pedigree.objects.filter(reg_no='PED-CASCADE').exists())

    def test_set_null_on_breeder_delete(self):
        breeder = Breeder.objects.create(account=self.account, breeding_prefix='TEMP')
        p = Pedigree.objects.create(reg_no='PED-SETNULL', account=self.account, breeder=breeder)
        breeder.delete()
        p.refresh_from_db()
        self.assertIsNone(p.breeder)

    def test_sale_or_hire_default_false(self):
        self.assertFalse(self.pedigree.sale_or_hire)

    def test_paid_default_false(self):
        self.assertFalse(self.pedigree.paid)


class PedigreeImageModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            ordering=1,
            service_name='Img Test Service',
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
        cls.user = User.objects.create_user(username='imguser', password='testpass123')
        cls.user_detail = UserDetail.objects.create(user=cls.user, phone='1234567890')
        cls.account = AttachedService.objects.create(
            user=cls.user_detail,
            service=cls.service,
            domain='https://imgtest.cloud-lines.com',
            animal_type='poultry',
            active=True,
        )
        cls.pedigree = Pedigree.objects.create(
            reg_no='IMG-PED-001',
            account=cls.account,
        )
        cls.pedigree_image = PedigreeImage.objects.create(
            reg_no=cls.pedigree,
            account=cls.account,
            title='Test Image',
        )

    def test_str_returns_reg_no(self):
        self.assertEqual(str(self.pedigree_image), 'IMG-PED-001')

    def test_default_state_is_approved(self):
        self.assertEqual(self.pedigree_image.state, 'approved')

    def test_related_name_images(self):
        images = self.pedigree.images.all()
        self.assertEqual(images.count(), 1)
        self.assertEqual(images.first(), self.pedigree_image)

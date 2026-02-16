from rest_framework import serializers
from cloud_lines.models import LargeTierQueue
from reports.models import ReportQueue
from pedigree.models import Pedigree, PedigreeImage
from breeder.models import Breeder
from breed.models import Breed
from breed_group.models import BreedGroup
from birth_notifications.models import BirthNotification, BnChild
from cloud_lines.models import Service, Faq, Bolton, Update
from account.models import AttachedService
from metrics.models import KinshipQueue, DataValidatorQueue, StudAdvisorQueue
from django.contrib.auth.models import User


class ApiLargeTierQueueSerializer(serializers.ModelSerializer):
    class Meta:
        model = LargeTierQueue
        #fields = '__all__'
        fields = ('id',
                  'subdomain',
                  'user',
                  'user_detail',
                  'attached_service',
                  'build_state',
                  'build_status',
                  'percentage_complete',
                  'username',
                  'service_id',
                  'stripe_id',
                  'site_mode',
                  'animal_type',
                  'user_data',
                  'services_data')


class ApiReportQueueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportQueue
        fields = '__all__'


class ApiAttachedServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttachedService
        fields = '__all__'

    def update(self, instance, validated_data):
        instance.read_only_users.add(validated_data.get('read_only_users', instance.read_only_users)[0])
        return instance


class ApiPedigreeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pedigree
        #fields = '__all__'
        fields = ("id",
                  "state",
                  "reg_no",
                  "tag_no",
                  "name",
                  "description",
                  "date_of_registration",
                  "dob",
                  "dod",
                  "status",
                  "sex",
                  "litter_size",
                  "parent_father_notes",
                  "parent_mother_notes",
                  "breed_group",
                  "coi",
                  "mean_kinship",
                  "date_added",
                  "custom_fields",
                  "sale_or_hire",
                  "creator",
                  "account",
                  "breeder",
                  "current_owner",
                  "parent_father",
                  "parent_mother",
                  "breed",
                  "parent_father_reg_no",
                  "parent_father_name",
                  "parent_mother_reg_no",
                  "parent_mother_name",
                  "breeder_breeding_prefix",
                  "current_owner_breeding_prefix",
                  "breed_breed_name")

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # In list view, resolve parent_father ID to reg_no
        is_list_view = isinstance(self.instance, list)
        if is_list_view:
            parent_father_id = ret.pop('parent_father', None)
            parent_father = Pedigree.objects.filter(id=parent_father_id).first()
            ret["parent_father"] = parent_father.reg_no if parent_father else ""
        return ret


class ApiPedigreeImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PedigreeImage
        fields = '__all__'


class ApiBreederSerializer(serializers.ModelSerializer):
    class Meta:
        model = Breeder
        fields = '__all__'


class ApiBreedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Breed
        fields = '__all__'


class ApiBreedGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = BreedGroup
        fields = '__all__'


class ApiFaqSerializer(serializers.ModelSerializer):
    class Meta:
        model = Faq
        fields = '__all__'


class ApiBoltonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bolton
        fields = '__all__'


class ApiUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Update
        fields = '__all__'


class ApiAuthentication(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'


class ApiServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ('service_name',
                  'price_per_month',
                  'admin_users',
                  'contrib_users',
                  'read_only_users',
                  'number_of_animals',
                  'multi_breed',
                  'active')


class ApiKinshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = KinshipQueue
        fields = '__all__'


class ApiDataValidationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataValidatorQueue
        fields = '__all__'


class ApiStudAdvisorSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudAdvisorQueue
        fields = '__all__'


class ApiBirthNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BirthNotification
        fields = '__all__'

class ApiBnChildSerializer(serializers.ModelSerializer):
    class Meta:
        model = BnChild
        fields = '__all__'
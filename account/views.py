from django.shortcuts import HttpResponse
from django.contrib.auth import login, authenticate
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.utils.datastructures import MultiValueDictKeyError
from django.core import serializers
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.core.exceptions import PermissionDenied
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib import auth
from django.db.models import Q
from django.conf import settings as django_settings
from rest_framework.authtoken.models import Token
from .models import UserDetail, AttachedService
from memberships.models import Membership
from cloud_lines.models import Service, Page
from pedigree.models import Pedigree
from pedigree.functions import get_pedigree_column_headings
from breed.models import Breed
from breeder.models import Breeder
from approvals.models import Approval
from money import Money
from re import match
from urllib.parse import urljoin
from threading import Thread
from cloudlines.constants import ServiceNames, BoltonTypes, SiteModes, DEFAULT_ANIMAL_TYPE
import random
import string
import stripe
import time
import json
import requests
import logging
from datetime import datetime

from django.contrib.auth import REDIRECT_FIELD_NAME
from django.shortcuts import resolve_url
from django.contrib.auth.views import redirect_to_login


logger = logging.getLogger(__name__)


def site_mode(request):
    # get gdpr
    try:
        gdpr = Page.objects.get(title='gdpr')
    except Page.DoesNotExist:
        gdpr = ''

    if request.user.is_authenticated:
        # returns the main account the requesting user is a member of
        attached_service = get_main_account(request.user)

        # returns the user for the main account
        user = UserDetail.objects.get(user=attached_service.user.user)
        user_detail = UserDetail.objects.get(user=request.user)

        attached_services = AttachedService.objects.filter(Q(admin_users=request.user, active=True) |
                                                           Q(contributors=request.user, active=True) |
                                                           Q(read_only_users=request.user, active=True)|
                                                           Q(user=user_detail, active=True)).distinct()

        breeds = Breed.objects.filter(account=attached_service, breed_admins__in=[request.user])

        # get user permission level
        editor = False
        breeds_editable = []
        contributor = False
        read_only = False
        if str(request.user.username) == str(user.user.username):
            editor = True
        elif request.user in attached_service.admin_users.all():
            editor = True
        elif breeds.exists():
            for breed in breeds:
                breeds_editable.append(breed.breed_name)
        elif request.user in attached_service.contributors.all():
            contributor = True
        elif request.user in attached_service.read_only_users.all():
            read_only = True
        else:
            editor = False
            contributor = False
            read_only = False

        # check for approvals
        if editor:
            if Approval.objects.all().count() > 0:
                pending_approvals = True
            else:
                pending_approvals = False
        else:
            pending_approvals = False

        if attached_service.service.service_name not in ServiceNames.UNLIMITED_ANIMAL_TIERS:
            if Pedigree.objects.filter(account=attached_service).count() < attached_service.service.number_of_animals:
                pedigrees = True
            else:
                pedigrees = False
        else:
            pedigrees = True

        if attached_service.admin_users.all().count() < attached_service.service.admin_users:
            admins = True
        else:
            admins = False

        if attached_service.read_only_users.all().count() < attached_service.service.read_only_users:
            users = True
        else:
            users = False

        if not attached_service.service.multi_breed:
            if Breed.objects.filter(account=attached_service).count() < 1:
                add_breed = True
            else:
                add_breed = False
        else:
            add_breed = True

        # boltons
        # default values
        birth_notification = False

        return {'service': attached_service,
                'attached_services': attached_services,
                'birth_notification': attached_service.boltons.filter(bolton=BoltonTypes.BIRTH_NOTIFICATION).exists(),
                'add_pedigree': pedigrees,
                'admins': admins,
                'users': users,
                'add_breed': add_breed,
                'editor': editor,
                'breeds_editable': breeds_editable,
                'contributor': contributor,
                'read_only': read_only,
                #'gdpr': gdpr,
                'pending_approvals': pending_approvals}

    return {'authenticated': 'no',
            'gdpr': gdpr}


def is_editor(user):
    try:
        main_account = get_main_account(user)
        try:
            editors = main_account.admin_users.all()
        except AttributeError:
            # no admin users!
            editors = []

        try:
            contributors = main_account.contributors.all()
        except AttributeError:
            # no admin users!
            contributors = []

        if user in editors or user in contributors:
            return True
        elif user == main_account.user.user:
            return True
        else:
            return False
    except UserDetail.DoesNotExist:
        return False
    except AttachedService.DoesNotExist:
        return False


def has_permission(request, permissions, pedigrees=[], breeder_users=[]):
    has_permission = False

    try:
        account = get_main_account(request.user)

        # go through each user type and allow access accordingly
        if request.user == account.user.user:
            has_permission = True
        elif request.user in account.admin_users.all():
            if permissions['admin']:
                has_permission = True
        # if user is a breed admin
        elif Breed.objects.filter(account=account, breed_admins__in=[request.user]).exists():

            # if it's a straight yes or no
            if permissions['breed_admin'] in (True, False):
                if permissions['breed_admin']:
                    # if breed admins are always allowed, grant permission
                    has_permission = True
            # if particular breed required
            else:
                breed_permission = True
                for pedigree in pedigrees:
                    if pedigree.breed:
                        if request.user not in pedigree.breed.breed_admins.all():
                            # if breed admin is not an admin of the correct breed, deny permission
                            breed_permission = False
                            break
                    else:
                        # breed of pedigree not set
                        breed_permission = False
                        break
                if breed_permission:
                    # if user is breed admin of all required breeds, grant permission
                    has_permission = True
        elif request.user in account.contributors.all():
            if permissions['contrib'] in (True, False):
                if permissions['contrib']:
                    has_permission = True
            elif request.user in breeder_users:
                has_permission = True
        elif request.user in account.read_only_users.all():
            if permissions['read_only'] in (True, False):
                if permissions['read_only']:
                    has_permission = True
            elif request.user in breeder_users:
                has_permission = True

    except UserDetail.DoesNotExist:
        pass
    except AttachedService.DoesNotExist:
        pass

    return has_permission


def redirect_2_login(request):
    return redirect_to_login(request.build_absolute_uri(), resolve_url('/account/login'), REDIRECT_FIELD_NAME)


def get_main_account(user):
    # get detail for logged in user
    user_detail = UserDetail.objects.get(user=user)
    try:
        # get attached service of the primary user
        attached_service = AttachedService.objects.get(id=user_detail.current_service_id, active=True)
    except AttachedService.DoesNotExist:
        # update the attached service to what default
        attached_service, created = AttachedService.objects.get_or_create(user=user_detail,
                                                                          animal_type=DEFAULT_ANIMAL_TYPE,
                                                                          site_mode=SiteModes.MAMMAL,
                                                                          service=Service.objects.get(service_name=ServiceNames.FREE))
        attached_service.install_available = False
        attached_service.active = True
        attached_service.save()
        user_detail.current_service = attached_service
        user_detail.save()

    return attached_service


def get_stripe_secret_key(request):
    if request.META['HTTP_HOST'] in django_settings.TEST_STRIPE_DOMAINS:
        return django_settings.STRIPE_TEST_SECRET_KEY
    else:
        return django_settings.STRIPE_SECRET_KEY


def get_stripe_public_key(request):
        if request.META['HTTP_HOST'] in django_settings.TEST_STRIPE_DOMAINS:
            return django_settings.STRIPE_TEST_PUBLIC_KEY
        else:
            return django_settings.STRIPE_PUBLIC_KEY


@login_required(login_url="/account/login")
def user_edit(request):
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            return HttpResponse(json.dumps({'success': False}))
    else:
        raise PermissionDenied()
    
    # this is the additional user customers can add/remove from their service.
    main_account = get_main_account(request.user)
    user_detail = UserDetail.objects.get(user=request.user)
    
    # validate breeder, if given
    breeder = None
    if request.POST.get('breeding_prefix') != '':
        breeder = Breeder.objects.filter(account=main_account, breeding_prefix=request.POST.get('breeding_prefix'))
        if breeder.exists():
            breeder = breeder.first()
            if breeder.user and request.POST.get('formType') == 'new':
                # error because breeder already has a user
                return HttpResponse(json.dumps({'fail': True, 'msg': 'A User is already assigned to this Breeder!'}))
        else:
            # error because breeder doesn't exist
            return HttpResponse(json.dumps({'fail': True, 'msg': 'Breeding Prefix does not match an existing Breeder!'}))
    
    if request.POST.get('formType') == 'new':
        # generate password
        password = ''.join(
            [random.choice(string.ascii_letters + string.digits + string.punctuation) for n in range(int(10))])

        # create new user
        new_user = User.objects.create_user(username=request.POST.get('register-form-username').lower(),
                                            email=request.POST.get('register-form-email'),
                                            password=password,
                                            first_name=request.POST.get('firstName'),
                                            last_name=request.POST.get('lastName'))

        # update user details
        new_user_detail = UserDetail.objects.create(user=new_user,
                                                    phone='',
                                                    )
        attached_service = AttachedService.objects.filter(user=new_user_detail).update(animal_type=DEFAULT_ANIMAL_TYPE,
                                                                                        install_available=False,
                                                                                        active=True)
        new_user_detail.current_service_id = user_detail.current_service_id
        new_user_detail.save()
        if request.POST.get('status') == 'Editor':
            main_account.admin_users.add(new_user)

        elif request.POST.get('status') == 'Breed Editor':
            for breed in Breed.objects.filter(account=main_account):
                if request.POST.get(breed.breed_name):
                    breed.breed_admins.add(new_user)
                    breed.save()

        elif request.POST.get('status') == 'Contributor':
            main_account.contributors.add(new_user)

        else:
            main_account.read_only_users.add(new_user)

        # set breeder
        if request.POST.get('breeding_prefix') != '':
            breeder.user = new_user
            breeder.save()

        # send email to new user
        if main_account.domain:
            domain = main_account.domain
        else:
            domain = 'https://cloud-lines.com'
        email_body = """
                    <p><strong>You have been registered on Cloud-lines by {}!</strong></p>

                    <p>Now that you have been registered you will need to set your own secure password.</p>
                    
                    <p><strong>Username: </strong>{}</p>

                    <p><a href="{}">Click here</a> to reset your password.</p>
                    
                    <p><a href="{}">Or Click here</a> to to login.</p>

                    <p>Feel free to contact us about anything and enjoy!</p>""".format(request.user.get_full_name(),
                                                                                        new_user.username,
                                                                                        urljoin(domain, 'accounts/password_reset/'),
                                                                                        domain)
        if not django_settings.DEBUG:
            send_mail('Welcome to Cloud-lines!', new_user.get_full_name(), email_body, send_to=new_user.email)
        return HttpResponse(json.dumps({'success': True}))

    elif request.POST.get('formType') == 'edit':
        # find user and update name fields
        User.objects.filter(username=request.POST.get('register-form-username'),
                            email=request.POST.get('register-form-email')).update(first_name=request.POST.get('firstName'),
                                                                                    last_name=request.POST.get('lastName'))
        existing_user = User.objects.get(username=request.POST.get('register-form-username'),
                                email=request.POST.get('register-form-email'))

        # check breeder doesn't already have a user other than the edited user
        if breeder:
            if breeder.user and breeder.user != existing_user:
                # error because breeder already has a user
                return HttpResponse(json.dumps({'fail': True, 'msg': 'A User is already assigned to this Breeder!'}))

        # remove user from breeds
        for breed in Breed.objects.filter(account=main_account):
            if not request.POST.get(breed.breed_name):
                breed.breed_admins.remove(existing_user)
                breed.save()

        # add user to the request group
        if request.POST.get('status') == 'Editor':
            main_account.admin_users.add(existing_user)
            # remove from other permissions
            main_account.read_only_users.remove(existing_user)
            main_account.contributors.remove(existing_user)
        elif request.POST.get('status') == 'Breed Editor':
            for breed in Breed.objects.filter(account=main_account):
                if request.POST.get(breed.breed_name):
                    breed.breed_admins.add(existing_user)
                    breed.save()
            # remove from other permissions
            main_account.admin_users.remove(existing_user)
            main_account.read_only_users.remove(existing_user)
            main_account.contributors.remove(existing_user)
        elif request.POST.get('status') == 'Contributor':
            main_account.contributors.add(existing_user)
            # remove from other permissions
            main_account.admin_users.remove(existing_user)
            main_account.read_only_users.remove(existing_user)
        else:
            main_account.read_only_users.add(existing_user)
            # remove from other permissions
            main_account.admin_users.remove(existing_user)
            main_account.contributors.remove(existing_user)
        main_account.save()

        # set breeder
        # get old breeder and prefix if exists
        old_breeder = existing_user.breeder.all()
        if old_breeder.exists():
            # unset old breeder
            old_breeder = old_breeder.first()
            old_breeder.user = None
            old_breeder.save()
        # set new breeder, if given
        if breeder:
            breeder.user = existing_user
            breeder.save()

        return HttpResponse(json.dumps({'success': True}))

    elif request.POST.get('formType') == 'delete':

        User.objects.get(username=request.POST.get('register-form-username'),
                            email=request.POST.get('register-form-email')).delete()

        return HttpResponse(json.dumps({'success': True}))


@login_required(login_url="/account/login")
def update_user(request):
    # where the user can update their own basic information
    if request.method == 'POST':
        # update user and get user object
        user = User.objects.get(username=request.user.username)
        user.first_name = request.POST.get('user-settings-first-name')
        user.last_name = request.POST.get('user-settings-last-name')
        user.email = request.POST.get('user-settings-email')
        # set users password
        if request.POST.get('user-settings-password') != "":
            user.set_password(request.POST.get('user-settings-password'))
        user.save()

        # update user details
        user_detail = UserDetail.objects.get(user=user)
        user_detail.phone = request.POST.get('user-settings-phone')
        user_detail.save()

        # authenticate to prevent relogging in
        authenticate(username=request.user.username, password=request.POST.get('user-settings-password'))
        login(request, user)

        return HttpResponse(True)

    raise PermissionDenied()


def site_login(request):
    if request.method == 'POST':
        user = auth.authenticate(username=request.POST['username'], password=request.POST['password'])
        if user is not None:
            user_detail =  UserDetail.objects.get(user=user)
            # set privacy agreed if it was agreed to
            if request.POST.get('privacy'):
                user_detail.privacy_agreed = datetime.now()
                user_detail.privacy_version = get_privacy_version()
                user_detail.save()
            # set data protection agreed if it was agreed to
            if request.POST.get('data_protection'):
                user_detail.data_protection_agreed = datetime.now()
                user_detail.data_protection_version = get_data_protection_version()
                user_detail.save()
            
            # check if need to agree with privacy policy (if they haven't agreed to the latest)
            privacy_needed = True
            if get_privacy_version() == user_detail.privacy_version and user_detail.privacy_agreed:
                privacy_needed = False
            
            # check if need to agree with data protection policy
            data_protection_needed = True
            # if they are not an owner or they have agreed to the latest
            if (not AttachedService.objects.filter(user=user_detail).exists()) or \
                        (get_data_protection_version() == user_detail.data_protection_version and user_detail.data_protection_agreed):
                data_protection_needed = False
            
            # go back to login if user needs to agree
            if privacy_needed or data_protection_needed:
                # large tier
                if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
                    return render(request, 'lt_login.html', {'error': 'Tick if you agree with the above.',
                        'privacy_needed': privacy_needed, 'data_protection_needed': data_protection_needed,
                        'detail': user_detail
                    })
                # small tier
                else:
                    return render(request, 'cl_login.html', {'error': 'Tick if you agree with the above.',
                        'privacy_needed': privacy_needed, 'data_protection_needed': data_protection_needed,
                        'detail': user_detail
                    })
            
            # log in and go to dashboard
            auth.login(request, user)
            return redirect('dashboard')
        else:
            if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
                return render(request, 'lt_login.html', {'error': 'Username or Password does not exist.'})
            else:
                return render(request, 'cl_login.html', {'error': 'Username or Password does not exist.'})
    else:
        if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
            attachedservice = AttachedService.objects.filter(domain__icontains=request.META['HTTP_HOST']).first()
            return render(request, 'lt_login.html', {"attachedservice": attachedservice})
        else:
            if request.GET.get('service'):
                service_id = request.GET.get('service')
                requested_service = Service.objects.get(id=service_id)
            else:
                requested_service = False
            return render(request, 'cl_login.html', {'requested_service': requested_service})


@login_required(login_url="/account/login")
def logout(request):
    # TO DO need to go to homepage and logout
    # if request.method == 'POST':
    auth.logout(request)
    return redirect('home')


@login_required(login_url="/account/login")
def profile(request):
    from django.conf import settings

    if request.META['HTTP_HOST'] in settings.TEST_STRIPE_DOMAINS:
        stripe_pk = settings.STRIPE_TEST_PUBLIC_KEY
        stripe.api_key = settings.STRIPE_TEST_SECRET_KEY
    else:
        stripe_pk = settings.STRIPE_PUBLIC_KEY
        stripe.api_key = settings.STRIPE_SECRET_KEY

    main_account = get_main_account(request.user)

    # Check if this request is the return from Stripe's Checkout success URL
    if request.GET.get('session_id'):
        session_id = request.GET['session_id']

        # Retrieve the Checkout session
        session = stripe.checkout.Session.retrieve(session_id)
        
        # Ensure session contains a setup_intent
        if session.setup_intent:
            setup_intent = stripe.SetupIntent.retrieve(session.setup_intent)
            
            # Set the payment method as the default for the customer
            stripe.Customer.modify(
                main_account.user.stripe_id,
                invoice_settings={
                    'default_payment_method': setup_intent.payment_method,
                },
            )

    context = {'public_api_key': stripe_pk, 'user_detail': UserDetail.objects.get(user=request.user)}

    if request.user == main_account.user.user and context['user_detail'].current_service.service.service_name != ServiceNames.FREE:
        context['services'] = Service.objects.exclude(service_name=ServiceNames.FREE)
        if main_account.service.service_name != ServiceNames.ORGANISATION:
            context['recommended'] = Service.objects.filter(id=main_account.service.id+1)
        else:
            context['recommended'] = None

        # billing
        try:
            charges = stripe.Charge.list(customer=main_account.user.stripe_id)

            for charge in charges:
                # convert to readable format
                charge_obj = Money(amount=str(charge['amount'] / 100), currency=str(charge['currency']).upper())
                charge['amount'] = charge_obj.format(
                    'en_{}'.format(charge['payment_method_details']['card']['country']))
                # convert data to readable format
                date = time.strftime('%d-%m-%Y', time.localtime(charge.created))
                charge['created'] = date
                # get invoice pdf
                if charge['invoice']:
                    invoice = stripe.Invoice.retrieve(charge['invoice'])
                    charge['invoice'] = invoice.invoice_pdf

            context['charges'] = charges
        except stripe.error.AuthenticationError:
            logger.error('Stripe authentication error')
            pass

        # payment methods
        try:
            customer = stripe.Customer.retrieve(main_account.user.stripe_id)

            # The `invoice_settings.default_payment_method` might contain the default card
            default_payment_method_id = customer.get("invoice_settings", {}).get("default_payment_method")

            if default_payment_method_id:
                context['card'] = stripe.PaymentMethod.retrieve(default_payment_method_id)

        except stripe.error.AuthenticationError:
            pass

    return render(request, 'profile.html', context)


@login_required(login_url="/account/login")
def settings(request, msg=''):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    else:
        raise PermissionDenied()
    
    
    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)

    custom_fields = user_detail.current_service.custom_fields
    try:
        custom_fields = json.loads(custom_fields)
    except:
        pass

    active_pedigree_columns = attached_service.pedigree_columns.split(',')

    breeds = []
    breed_admins = []
    for breed in Breed.objects.filter(account=attached_service):
        # add each breed to context
        breeds.append(breed)
        for breed_admin in breed.breed_admins.all():
            if breed_admin not in breed_admins:
                # add each breed admin to context
                breed_admins.append(breed_admin)

    try:
        boltons = requests.get(django_settings.BOLTON_API_URL).json()
        count = 0
        for bolton in boltons['results']:
            if attached_service.boltons.filter(bolton=bolton['id'], active=True).exists():
                boltons['results'][count]['active'] = True
            count += 1
    except:
        boltons = []

    # memberships
    # validate active membership bolton exists
    if attached_service.boltons.filter(bolton=BoltonTypes.MEMBERSHIPS, active=True).exists():
        try:
            # get the membership objects
            membership, created = Membership.objects.get_or_create(account=attached_service)
            # get or create a token
            membership.get_or_create_token()
        except Membership.DoesNotExist:
            membership = None
    else:
        membership = None

    return render(request, 'settings.html', {'custom_fields': custom_fields,
                                             'pedigree_headings': get_pedigree_column_headings(),
                                             'active_pedigree_columns': active_pedigree_columns,
                                             'breeds': breeds,
                                             'breed_admins': breed_admins,
                                             'boltons': boltons,
                                             'membership': membership,
                                             'msg': msg})


@user_passes_test(is_editor, "/account/login")
@login_required(login_url="/account/login")
def custom_field_edit(request):
    # permission check (only post allowed)
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            return HttpResponse(json.dumps({'fail': True}))
    else:
        raise PermissionDenied()

    # this is the additional user customers can add/remove from their service.
    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)
    if user_detail.current_service.custom_fields:
        custom_fields = json.loads(user_detail.current_service.custom_fields)
    else:
        custom_fields = {}

    if request.POST.get('formType') == 'new':
        # create unique key
        for suffix in range(0, len(custom_fields)+2):
            if 'cf_{}'.format(suffix) not in custom_fields:
                field_key = 'cf_{}'.format(suffix)
                break

        custom_fields[field_key] = {'id': field_key,
                                    'location': request.POST.get('location'),
                                    'fieldName': request.POST.get('fieldName'),
                                    'fieldType': request.POST.get('fieldType'),
                                    'incCert': request.POST.get('incCert')}
        attached_service.custom_fields = json.dumps(custom_fields)
        attached_service.save()

        Thread(target=update_custom_fields, args=(request, attached_service)).start()
        return HttpResponse(json.dumps({'success': True}))

    elif request.POST.get('formType') == 'edit':
        custom_fields[request.POST.get('id')] = {'id': request.POST.get('id'),
                                                 'location': request.POST.get('location'),
                                                 'fieldName': request.POST.get('fieldName'),
                                                 'fieldType': request.POST.get('fieldType'),
                                                 'incCert': request.POST.get('incCert')}
        attached_service.custom_fields = json.dumps(custom_fields)
        attached_service.save()

        Thread(target=update_custom_fields, args=(request, attached_service)).start()
        return HttpResponse(json.dumps({'success': True}))

    elif request.POST.get('formType') == 'delete':
        custom_fields.pop(request.POST.get('id'), None)
        attached_service.custom_fields = json.dumps(custom_fields)
        attached_service.save()

        Thread(target=update_custom_fields, args=(request, attached_service)).start()
        return HttpResponse(json.dumps({'success': True}))


def update_custom_fields(request, attached_service):
    token, created = Token.objects.get_or_create(user=request.user)
    data = '{"domain": "%s", "account": %s, "token": "%s"}' % (attached_service.domain, attached_service.id, token)

    # get auth token
    token_res = requests.post(url=urljoin(django_settings.ORCH_URL, '/api-token-auth/'),
                              data={'username': django_settings.ORCH_USER, 'password': django_settings.ORCH_PASS})
    ## create header
    headers = {'Content-Type': 'application/json', 'Authorization': f"token {token_res.json()['token']}"}
    post_res = requests.post(url=urljoin(django_settings.ORCH_URL, '/api/custom_fields/update_fields/'), headers=headers,
                             data=data)


@login_required(login_url="/account/login")
def update_titles(request):
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()
    
    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)
    attached_service.mother_title = request.POST.get('mother')
    attached_service.father_title = request.POST.get('father')
    attached_service.save()

    return HttpResponse('Done')


@login_required(login_url="/account/login")
def update_name(request):
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)
    attached_service.organisation_or_society_name = request.POST.get('organisation_or_society_name')
    attached_service.save()

    return HttpResponse('Done')


@login_required(login_url="/account/login")
def update_pedigree_columns(request):
    # check if user has permission
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': True}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)
    columns = request.POST['columns']
    attached_service.pedigree_columns = str(columns)
    attached_service.save()

    return HttpResponse('Done')


@login_required(login_url="/account/login")
def logo_upload(request):
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': True}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    attached_service = get_main_account(request.user)

    image = request.FILES['file[0]']
    from PIL import Image
    #from PIL.Image import core as _imaging
    from django.core.files.base import ContentFile
    import pyheif
    from io import BytesIO
    from os import path

    filename, file_extension = path.splitext(str(request.FILES['file[0]']))
    if file_extension == ".HEIC":
        img_io = BytesIO()
        heif_file = pyheif.read(request.FILES['file[0]'])
        image = Image.frombytes(mode=heif_file.mode, size=heif_file.size, data=heif_file.data)
        image.save(img_io, format='JPEG', quality=100)
        image = ContentFile(img_io.getvalue(), f"{filename}.jpeg")

    attached_service.image = image
    attached_service.save()
    return HttpResponse('')


@login_required(login_url="/account/login")
def metrics_switch(request):
    # permission check
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()
    
    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)
    attached_service.metrics = request.POST.get('isEnabled') == 'true'
    attached_service.save()
    return HttpResponse('')


@login_required(login_url="/account/login")
def pedigree_charging_switch(request):
    # permission check
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)
    attached_service.pedigree_charging = request.POST.get('isEnabled') == 'true'
    attached_service.save()
    return HttpResponse('')


@login_required(login_url="/account/login")
def pedigrees_visible_switch(request):
    # permission check
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    user_detail = UserDetail.objects.get(user=request.user)
    attached_service = AttachedService.objects.get(id=user_detail.current_service_id)
    attached_service.pedigrees_visible = request.POST.get('isEnabled') == 'true'
    attached_service.save()
    return HttpResponse('')

@login_required(login_url="/account/login")
def welcome(request):
    return render(request, 'welcome.html')


def register(request):
    if request.method == 'POST':
        # validate 'i am a robot'
        google_post_url = 'https://www.google.com/recaptcha/api/siteverify'
        params = {'secret': django_settings.IANAR_SECRET_KEY,
                  'response': request.POST.get('g-recaptcha-response')}
        google_response = requests.get(url=google_post_url, params=params)
        google_response_json = google_response.json()

        # if google response good!
        if google_response_json['success']:
            # check user has agreed to both things
            if not request.POST.get('privacy') or not request.POST.get('data_protection'):
                return redirect('cl_login')
            
            username = request.POST.get('register-form-username')
            raw_password = request.POST.get('register-form-password')
            email = request.POST.get('register-form-email')
            User.objects.create_user(username=username,
                                     email=email,
                                     password=raw_password,
                                     first_name=request.POST.get('register-form-first-name'),
                                     last_name=request.POST.get('register-form-last-name'))
            user = authenticate(username=username, password=raw_password)

            # update user details
            user_detail = UserDetail.objects.create(user=user,
                                                    phone=request.POST.get('register-form-phone'),
                                                    privacy_agreed=datetime.now(),
                                                    privacy_version=get_privacy_version(),
                                                    data_protection_agreed=datetime.now(),
                                                    data_protection_version=get_data_protection_version())
            # login
            login(request, user)

            UserDetail.objects.filter(user=user).update(current_service=AttachedService.objects.create(animal_type=DEFAULT_ANIMAL_TYPE,
                                                                                                       site_mode=SiteModes.MAMMAL,
                                                                                                       install_available=False,
                                                                                                       user=user_detail,
                                                                                                       service=Service.objects.get(service_name=ServiceNames.FREE),
                                                                                                       active=True))
            # login
            login(request, user)


            email_body = """
            <p>Dear {}({}),
            <p><strong>Thank you for registering with Cloud-lines!</strong></p>
            
            <p>Now that you have registered you have access to our Free service.</p>
            
            <p><a href="https://cloud-lines.com/dashboard">Click here</a> to go to your new dashboard.</p>
            
            <p>Feel free to contact us about anything and enjoy!</p>""".format(user.get_full_name(), user.username)

            if 'localhost' not in request.build_absolute_uri():
                if not django_settings.DEBUG:
                    send_mail('Welcome to Cloud-lines!', user.get_full_name(), email_body, send_to=user.email)
                    send_mail('New site registration', user.get_full_name(), email_body, reply_to=user.email)

            if request.POST.get("service"):
                return redirect('order', request.POST.get("service"))
            else:
                return redirect('order')
        else:
            return redirect('cl_login')
    else:
        return redirect('cl_login')


@csrf_exempt
def username_check(request):
    if request.method == 'POST':
        username = request.POST.get('register-form-username')
        return HttpResponse(User.objects.filter(username=username).exists())


@csrf_exempt
def email_check(request):
    if request.method == 'POST':
        email = request.POST.get('register-form-email')
        return HttpResponse(User.objects.filter(email=email).exists())


@csrf_exempt
def subdomain_check(request):
    if request.method == 'POST':
        domain = request.POST.get('checkout-form-sub-domain')
        return HttpResponse(AttachedService.objects.filter(domain='https://{}.cloud-lines.com'.format(domain)).exists())


@login_required(login_url="/account/login")
def update_card(request):
    # permission check
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            raise PermissionDenied()
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    stripe.api_key = get_stripe_secret_key(request)
    
    user_detail = UserDetail.objects.get(user=request.user)

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='setup',
        customer=user_detail.stripe_id,
        success_url=f"http://{request.META['HTTP_HOST']}/account/profile#billing?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"http://{request.META['HTTP_HOST']}/account/profile#billing",
    )
    return redirect(session.url, code=303)


@login_required(login_url="/account/login")
@csrf_exempt
def cancel_sub(request):
    # permission check
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            return redirect_2_login(request)
    else:
        raise PermissionDenied()
    
    from django.conf import settings
    if self.request.META['HTTP_HOST'] in settings.TEST_STRIPE_DOMAINS:
        stripe.api_key = settings.STRIPE_TEST_SECRET_KEY
    else:
        stripe.api_key = settings.STRIPE_SECRET_KEY
    attached_service = get_main_account(request.user)
    stripe.Subscription.delete(attached_service.subscription_id)
    attached_service.active = False
    attached_service.save()
    result = {'result': 'canceled'}
    return HttpResponse(json.dumps(result))


def send_mail(subject, name, body,
              send_to='contact@masys.co.uk',
              send_from='contact@masys.co.uk',
              reply_to='contact@masys.co.uk'):

    html_content = render_to_string('mail/email.html', {'name': name,
                                                       'body': body})
    text_content = strip_tags(html_content)

    # create the email, and attach the HTML version as well.
    msg = EmailMultiAlternatives(subject, text_content, send_from, [send_to], reply_to=[reply_to])
    msg.attach_alternative(html_content, "text/html")

    msg.send()

    return


@login_required(login_url="/account/login")
@user_passes_test(is_editor, "/account/login")
@never_cache
def get_user_details(request):
    # get the user that was input
    try:
        user = User.objects.get(username=request.GET['id'])
    except User.DoesNotExist:
        return HttpResponse(json.dumps({'result': 'fail'}))
    except MultiValueDictKeyError:
        return HttpResponse(json.dumps({'result': 'fail'}))
    
    user = serializers.serialize('json', [user], ensure_ascii=False)
    return HttpResponse(json.dumps({'result': 'success',
                                    'user': user}))


def get_privacy_version():
    return '2.0'

def get_data_protection_version():
    return '2.0'

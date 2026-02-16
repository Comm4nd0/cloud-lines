from django.shortcuts import render, redirect, HttpResponse
from django.http import JsonResponse
from django.db import IntegrityError
from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.generic.base import TemplateView
from django.conf import settings
from account.views import is_editor,\
    get_main_account,\
    has_permission,\
    redirect_2_login,\
    get_stripe_secret_key,\
    get_stripe_public_key

from account.models import AttachedBolton, StripeAccount
from account.currencies import get_currencies, get_countries
from account.stripe_charging import StripeAccountManager
from .models import BirthNotification, BnChild
from .forms import BirthNotificationForm
from .charging import *
from breeder.models import Breeder
from pedigree.models import Pedigree
from pedigree.pedigree_charging import get_pedigree_prices
from pedigree.views import create_approval
from pedigree.functions import get_next_reg
from json import dumps
from urllib.parse import urljoin
import requests
import re
from cloudlines.constants import BnChildStatus
import stripe


# Create your views here.
class BirthNotificationBase(LoginRequiredMixin, TemplateView):
    login_url = '/account/login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['attached_service'] = get_main_account(self.request.user)
        if context['attached_service'].pedigree_charging and is_editor(self.request.user):
            stripe_manager = StripeAccountManager(self.request, context['attached_service'])
            try:
                context['local_stripe_account'] = StripeAccount.objects.get(account=context['attached_service'])
            except StripeAccount.DoesNotExist:
                context['local_stripe_account'] = None
            context['edit_account'] = stripe_manager.get_account_edit_link()  # Edit existing stripe account
            context['countries'] = list(get_countries().values())
        
        # if self.request.user == context['attached_service'].user.user:
        #     context['stripe_account'], \
        #     context['account_link'], \
        #     context['stripe_package'], \
        #     context['edit_account'], \
        #     context['account_link_setup'] = get_stripe_connected_account_links(self.request,
        #                                                                        context['attached_service'])
        return context


class BnHome(BirthNotificationBase):
    template_name = 'bn_home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['birth_notifications'] = BirthNotification.objects.filter(account=context['attached_service'], paid=True)
        context['latest'] = context['birth_notifications'].filter(account=context['attached_service'], paid=True).order_by('-id')[:10]

        context['total_living'] = context['birth_notifications'].filter(births__status="alive", paid=True).count()
        context['total_deceased'] = context['birth_notifications'].filter(births__status=BnChildStatus.DECEASED, paid=True).count()
        context['approvals'] = BirthNotification.objects.filter(account=context['attached_service'], paid=True , complete=False)

        return context


class Settings(BirthNotificationBase):
    template_name = 'bn_settings.html'

    def get_context_data(self, **kwargs):
        # check if user has permission
        if self.request.method == 'GET':
            if not has_permission(self.request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': False}):
                return redirect_2_login(self.request)
        elif self.request.method == 'POST':
            if not has_permission(self.request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
                raise PermissionDenied()
        else:
            raise PermissionDenied()

        context = super().get_context_data(**kwargs)

        stripe.api_key = get_stripe_secret_key(self.request)

        context['currencies'] = get_currencies()

        context['bn_stripe_account'] = StripeAccount.objects.get(account=context['attached_service'])
        context['stripe_account'] = stripe.Account.retrieve(context['bn_stripe_account'].stripe_acct_id)

        # get bn price
        if context['bn_stripe_account'].bn_cost_id:
            context['bn_cost'] = stripe.Price.retrieve(
                context['bn_stripe_account'].bn_cost_id,
                stripe_account=context['bn_stripe_account'].stripe_acct_id
            ).unit_amount
        else:
            context['bn_cost'] = 0
        # get child price
        if context['bn_stripe_account'].bn_child_cost_id:
            context['bn_child_cost'] = stripe.Price.retrieve(
                context['bn_stripe_account'].bn_child_cost_id,
                stripe_account=context['bn_stripe_account'].stripe_acct_id
            ).unit_amount
        else:
            context['bn_child_cost'] = 0
        return context


@login_required(login_url="/account/login")
def update_prices(request):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    stripe.api_key = get_stripe_secret_key(request)

    attached_service = get_main_account(request.user)

    bn_stripe_account = StripeAccount.objects.get(account=attached_service)

    bn_stripe_account.currency = request.POST.get('currency')

    bn_stripe_account.bn_cost_id = stripe.Price.create(
        nickname="BN Price",
        unit_amount=int(float(request.POST.get('bncost')) * 100),
        currency=request.POST.get('currency'),
        product=bn_stripe_account.bn_stripe_product_id,
        stripe_account=bn_stripe_account.stripe_acct_id
    ).id

    bn_stripe_account.bn_child_cost_id = stripe.Price.create(
        nickname="BN Child Price",
        unit_amount=int(float(request.POST.get('bnccost')) * 100),
        currency=request.POST.get('currency'),
        product=bn_stripe_account.bn_stripe_product_id,
        stripe_account=bn_stripe_account.stripe_acct_id
    ).id
    bn_stripe_account.save()
    
    return redirect('bn_settings')


class BirthNotificationView(BirthNotificationBase):
    template_name = 'birth_notification.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['bn'] = BirthNotification.objects.get(id=self.kwargs['id'])

        # validate user can register pedigrees
        if context['bn'].mother and context['bn'].mother.breed:
            if self.request.user in context['bn'].mother.breed.breed_admins.all():
                # must also be a contrib or editor
                context['can_register'] = True
            else:
                context['can_register'] = False

            if context['attached_service'].pedigree_charging:
                context['prices'] = get_pedigree_prices(self.request, context['attached_service'])
        return context


@login_required(login_url="/account/login")
def birth_notification_form(request):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    attached_service = get_main_account(request.user)

    try:
        bn_stripe_account = StripeAccount.objects.get(account=attached_service)
    except StripeAccount.DoesNotExist:
        bn_stripe_account = False

    stripe.api_key = get_stripe_secret_key(request)

    # get bn price
    if bn_stripe_account.bn_cost_id not in ["", None]:
        bn_cost = stripe.Price.retrieve(
            bn_stripe_account.bn_cost_id,
            stripe_account=bn_stripe_account.stripe_acct_id
        )
    else:
        bn_cost = 0
    # get child price
    if bn_stripe_account.bn_child_cost_id not in ["", None]:
        bn_child_cost = stripe.Price.retrieve(
            bn_stripe_account.bn_child_cost_id,
            stripe_account=bn_stripe_account.stripe_acct_id
        )
    else:
        bn_child_cost = 0

    if request.method == 'POST':
        #bn_form = BirthNotificationForm(request.POST or None)
        bn_form = request.POST

        new_bn = BirthNotification()
        ### mother ###
        try:
            new_bn.mother = Pedigree.objects.get(account=attached_service,
                                                  reg_no=bn_form['motherx'])
        except:
            pass

        ### father ###
        try:
            new_bn.father = Pedigree.objects.get(account=attached_service,
                                                  reg_no=bn_form['fatherx'])
        except:
            pass

        new_bn.user = request.user
        new_bn.account = attached_service
        # not currently validating against other bn numbers on same instance
        new_bn.bn_number = bn_form['bn_number']
        if bn_form['dob'] != '':
            try:
                new_bn.dob = bn_form['dob']
            except KeyError:
                # no date added
                pass
        try:
            new_bn.comments = bn_form['comments']
        except KeyError:
            # no comment added
            pass

        try:
            new_bn.breeder = Breeder.objects.get(breeding_prefix=bn_form['breeder'])
        except Breeder.DoesNotExist:
            pass
        except KeyError:
            pass

        # needs to be moved to after adding children
        try:
            new_bn.save()
        except IntegrityError:
            result = {'result': 'fail',
                      'feedback': f'BN Number: {bn_form["bn_number"]} already in use!'}
            return HttpResponse(dumps(result))

        # births and calc total
        birth_line = 0
        bn_form_dict = dict(bn_form)
        for birth in bn_form_dict['tag_no']:
            child = BnChild.objects.create(tag_no=bn_form_dict['tag_no'][birth_line],
                                           status=bn_form_dict['status'][birth_line],
                                           sex=bn_form_dict['sex'][birth_line],
                                           for_sale=bn_form_dict['for_sale'][birth_line])
            new_bn.births.add(child)
            new_bn.save()
            birth_line += 1
        new_bn.save()

        # process payment
        if bn_stripe_account.bn_charging:
            user_detail = request.user.user.all()[0]

            # get or create customer
            if not user_detail.bn_stripe_id:
                customer = stripe.Customer.create(
                    email=user_detail.user.email,
                    stripe_account=bn_stripe_account.stripe_acct_id
                )
                user_detail.bn_stripe_id = customer['id']
            else:
                customer = stripe.Customer.retrieve(user_detail.bn_stripe_id,
                                                    stripe_account=bn_stripe_account.stripe_acct_id)
            # redirect to bn payment page
            return redirect('bn_checkout', new_bn.id, bn_stripe_account.bn_cost_id, bn_stripe_account.bn_child_cost_id, birth_line)

        else:
            # payment required, set paid to true to ensure visibility
            new_bn.paid = True
            new_bn.save()
            return redirect('birth_notification', new_bn.id)

    else:
        public_api_key = get_stripe_public_key(request)

        # get next available reg number
        try:
            latest_added = BirthNotification.objects.filter(account=attached_service).last()
            latest_reg = latest_added.bn_number
            reg_ints_re = re.search("[0-9]+", latest_reg)
            bn_number = latest_reg.replace(str(reg_ints_re.group(0)),
                                               str(int(reg_ints_re.group(0)) + 1).zfill(len(reg_ints_re.group(0))))
        except BirthNotification.DoesNotExist:
            bn_number = 'BN123456'
        except AttributeError:
            bn_number = 'BN123456'

        # if reg taken, increment until not taken
        if bn_number == 'BN123456':
            while BirthNotification.objects.filter(account=attached_service, bn_number=bn_number).exists():
                reg_ints_re = re.search("[0-9]+", bn_number)
                bn_number = bn_number.replace(str(reg_ints_re.group(0)),
                                                      str(int(reg_ints_re.group(0)) + 1).zfill(
                                                          len(reg_ints_re.group(0))))

        bn_form = BirthNotificationForm({'bn_number': bn_number})

    return render(request, 'birth_notification_form.html', {'bn_form': bn_form,
                                                            'bn_number': bn_number,
                                                            'public_api_key': public_api_key,
                                                            'bn_stripe_account': bn_stripe_account,
                                                            'bn_cost': bn_cost,
                                                            'bn_child_cost': bn_child_cost})


@login_required(login_url="/account/login")
def bn_checkout(request, id, bn_cost_id, bn_child_cost_id, no_of_child):
    attached_service = get_main_account(request.user)
    stripe_account = StripeAccount.objects.get(account=attached_service)
    return render(request, 'bn_checkout.html', {'bn_id': id,
                                                'bn_cost_id': bn_cost_id,
                                                'bn_child_cost_id': bn_child_cost_id,
                                                'no_of_child': no_of_child,
                                                'stripe_pk': get_stripe_public_key(request),
                                                'connect_account_id': stripe_account.stripe_acct_id})


@login_required(login_url="/account/login")
def birth_notification_paid(request, id):
    # return view from stripe on sucessful payment for a new birth notification
    BirthNotification.objects.filter(id=id).update(paid=True)
    return redirect('birth_notification', id)


@login_required(login_url="/account/login")
def enable_bn(request, id):
    # return view from stripe on successful payment of enabling the bn bolton
    attached_service = get_main_account(request.user)
    new_bolton = AttachedBolton.objects.get(id=id)
    new_bolton.active = True
    new_bolton.save()
    attached_service.boltons.add(new_bolton)

    # bolton = requests.get(urljoin(settings.BOLTON_API_URL, str(id))).json()

    # # send confirmation email
    # body = f"""<p>This email confirms the successful creation of your new Cloud-Lines bolton.

    #                 <ul>
    #                 <li>Bolton: {bolton['name']}</li>
    #                 <li>Monthly Cost: £{bolton['price']}</li>
    #                 </ul>

    #                 <p>Thank you for purchasing this boloton. Please contact us if you need anything - contact@masys.co.uk</p>

    #                 """
    # send_mail(f"New Bolton Added: {bolton['name']}",
    #            request.user.get_full_name(), body,
    #            send_to=request.user.email)

    return redirect('bn_home')


@login_required(login_url="/account/login")
def edit_child(request, id):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    if request.method == 'POST':
        child = BnChild.objects.get(id=id)
        child.tag_no = request.POST.get('tag_no')
        child.status = request.POST.get('status')
        child.sex = request.POST.get('sex')
        child.for_sale = request.POST.get('for_sale')
        child.comments = request.POST.get('comments')
        child.save()
    return redirect('birth_notification', child.births.all()[0].id)


@login_required(login_url="/account/login")
def delete_child(request, id):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': False}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    if request.method == 'GET':
        child = BnChild.objects.get(id=id)
        id = child.births.all()[0].id
        child.delete()
    return redirect('birth_notification', id)


@login_required(login_url="/account/login")
def register_pedigree(request, id, price):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    attached_service = get_main_account(request.user)

    child = BnChild.objects.get(id=id)

    new_pedigree = Pedigree.objects.create(account=attached_service,
                                           reg_no=get_next_reg(attached_service),
                                           tag_no=child.tag_no,
                                           status=child.status,
                                           sex=child.sex,
                                           parent_mother=child.births.all()[0].mother,
                                           parent_father=child.births.all()[0].father,
                                           breed=child.births.all()[0].mother.breed,
                                           sale_or_hire=child.for_sale,
                                           description=child.comments)

    # redirect for charging
    if attached_service.pedigree_charging:
        return redirect('rp_checkout', new_pedigree.id, price, child.id)
    else:
        new_pedigree.paid = True
        new_pedigree.save()
        child.pedigree = new_pedigree
        child.save()

        if request.user in attached_service.contributors.all():
            create_approval(request, new_pedigree, attached_service, state='unapproved', type='new')

    return redirect('birth_notification', child.births.all()[0].id)


@login_required(login_url="/account/login")
def rp_checkout(request, id, price, child_id):
    attached_service = get_main_account(request.user)
    stripe_account = StripeAccount.objects.get(account=attached_service)
    return render(request, 'rp_checkout.html', {'rp_id': id,
                                                'price': price,
                                                'child_id': child_id,
                                                'stripe_pk': get_stripe_public_key(request),
                                                'connect_account_id': stripe_account.stripe_acct_id})


@login_required(login_url="/account/login")
def register_pedigree_success(request, pedigree_id, child_id):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    stripe.api_key = get_stripe_secret_key(request)
    attached_service = get_main_account(request.user)
    stripe_account = StripeAccount.objects.get(account=attached_service)
    session = stripe.checkout.Session.retrieve(request.GET.get('session_id', ''),
                                               stripe_account=stripe_account.stripe_acct_id)

    child = BnChild.objects.get(id=child_id)
    pedigree = Pedigree.objects.get(id=pedigree_id)
    pedigree.stripe_payment_token = session.payment_intent
    pedigree.save()
    child.pedigree = pedigree
    child.save()

    if request.user in attached_service.contributors.all():
        create_approval(request, pedigree, attached_service, state='unapproved', type='new')
    return redirect('pedigree', pedigree_id)


@login_required(login_url="/account/login")
def approve_birth_notification(request, id):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    if request.method == 'GET':
        bn = BirthNotification.objects.get(id=id)
        bn.complete = True
        bn.save()
    return redirect(request.META.get('HTTP_REFERER', 'redirect_if_referer_not_found'))


@login_required(login_url="/account/login")
def edit_birth_notification(request, id):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    attached_service = get_main_account(request.user)
    print(request.POST.get('bn_breeder'))
    if request.method == 'POST':
        bn = BirthNotification.objects.get(id=id)
        bn.mother = Pedigree.objects.get(account=attached_service,
                                         reg_no=request.POST.get('motherx'))
        bn.father = Pedigree.objects.get(account=attached_service,
                                         reg_no=request.POST.get('fatherx'))
        bn.bn_number = request.POST.get('bn_number')
        bn.dob = request.POST.get('bn_dob')
        bn.comments = request.POST.get('comments')
        try:
            bn.breeder = Breeder.objects.get(breeding_prefix=request.POST.get('bn_breeder'))
        except Breeder.DoesNotExist:
            pass
        except KeyError:
            bn.breeder = None

        bn.save()
    return redirect('birth_notification', bn.id)


@login_required(login_url="/account/login")
def delete_birth_notification(request, id):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': True, 'breed_admin': False}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': False, 'admin': False, 'breed_admin': False}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    if request.method == 'GET':
        attached_service = get_main_account(request.user)
        bnstripeobject = StripeAccount.objects.get(account=attached_service)
        bn = BirthNotification.objects.get(id=id)

        if bnstripeobject.bn_cost_id or bnstripeobject.bn_child_cost_id:
            stripe.api_key = get_stripe_secret_key(request)
            # submit refund
            session = stripe.checkout.Session.retrieve(
                bn.stripe_payment_token,
                stripe_account=bnstripeobject.stripe_acct_id
            )

            if session['payment_status'] == 'paid':
                payment_intent = stripe.PaymentIntent.retrieve(
                    session.payment_intent,
                    stripe_account=bnstripeobject.stripe_acct_id
                )

                # create refund
                stripe.Refund.create(
                    charge=payment_intent['charges']['data'][0]['id'],
                    stripe_account=bnstripeobject.stripe_acct_id
                )
        bn.delete()
    return redirect('bn_home')


@login_required(login_url="/account/login")
def validate_bn(request, id):
    # return
    # true == in use
    # false == not in use
    attached_service = get_main_account(request.user)
    bn = BirthNotification.objects.get(account=attached_service, id=id)

    new_bn = list(request.GET.keys())[0]

    # if the bn number is its self, not in use
    if bn.bn_number == list(request.GET.keys())[0]:
        return HttpResponse(False)

    # check if bn number is in use
    try:
        bn_check = BirthNotification.objects.get(account=attached_service, bn_number=new_bn)
    except BirthNotification.DoesNotExist:
        # the bn number is not being used at all, not in use
        return HttpResponse(False)

    # if the bn check is the same as the main bn then it's not in use
    if bn.id == bn_check.id:
        return HttpResponse(False)

    # a bn was found and it's the same as the main bn then it's in use!
    return HttpResponse(True)


@login_required(login_url="/account/login")
def validate_bn_number(request):
    if request.POST:
        return JsonResponse({'result': BirthNotification.objects.filter(bn_number=request.POST.get('bn_number')).exists()})


@login_required(login_url="/account/login")
def bn_charging_switch(request):
    attached_service = get_main_account(request.user)
    bnstripeobject = StripeAccount.objects.get(account=attached_service)
    # validate a price has been set
    if bnstripeobject.bn_cost_id or bnstripeobject.bn_child_cost_id:
        if not bnstripeobject.bn_charging:
            bnstripeobject.bn_charging = True
        else:
            bnstripeobject.bn_charging = False
        bnstripeobject.save()
        return JsonResponse({'result': 'success'})
    else:
        return JsonResponse({'result': 'fail',
                             'error': 'At least one price must be set!'})
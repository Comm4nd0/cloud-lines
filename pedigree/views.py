from django.shortcuts import render, HttpResponse, redirect
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.base import TemplateView
from django.views.decorators.cache import never_cache
from django.utils.text import slugify
from django.core import serializers
from io import BytesIO
from django.template.loader import get_template
from django.views.generic import View
from xhtml2pdf import pisa
from .models import Pedigree, PedigreeImage

from breed.models import Breed
from breeder.models import Breeder
from breeder.forms import BreederForm
from breed.forms import BreedForm
from breed_group.models import BreedGroup
from .forms import PedigreeForm, ImagesForm
from .functions import get_site_pedigree_column_headings, get_next_reg
from .pedigree_charging import pedigree_charging_session,\
    get_pedigree_payment_session
from django.db.models import Q
import json
from account.currencies import get_countries
from account.models import StripeAccount
from cloudlines.constants import States, PedigreeSex, PedigreeStatus
from account.views import is_editor,\
    get_main_account,\
    has_permission,\
    redirect_2_login,\
    get_stripe_public_key
from account.stripe_charging import StripeAccountManager
from approvals.models import Approval
import dateutil.parser
from django.utils.datastructures import MultiValueDictKeyError


@login_required(login_url="/account/login")
def search(request):
    attached_service = get_main_account(request.user)
    columns, column_data = get_site_pedigree_column_headings(attached_service)

    if attached_service.pedigree_charging and is_editor(request.user):
        stripe_manager = StripeAccountManager(request, attached_service)
        try:
            local_stripe_account = StripeAccount.objects.get(account=attached_service)
        except StripeAccount.DoesNotExist:
            local_stripe_account = None
        edit_account = stripe_manager.get_account_edit_link()  # Edit existing stripe account

        return render(request, 'search.html', {'columns': columns,
                                               'column_data': column_data,
                                               'local_stripe_account': local_stripe_account,
                                               'edit_account': edit_account,
                                               'countries': list(get_countries().values())})
    else:
        return render(request, 'search.html', {'columns': columns,
                                               'column_data': column_data})


class PedigreeBase(LoginRequiredMixin, TemplateView):
    login_url = '/account/login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['attached_service'] = get_main_account(self.request.user)

        context['lvl1'] = Pedigree.objects.get(account=context['attached_service'], id=self.kwargs['pedigree_id'])

        # get any children
        context['children'] = Pedigree.objects.filter(Q(parent_father=context['lvl1'], account=context['attached_service']) | Q(parent_mother=context['lvl1'], account=context['attached_service']))

        # get attached groups
        context['groups'] = BreedGroup.objects.filter(group_members=context['lvl1'].id)

        # get all pedigrees for typeahead fields
        context['pedigrees'] = Pedigree.objects.filter(account=context['attached_service']).exclude(state=States.UNAPPROVED)

        # update and get custom fields
        try:
            #update_pedigree_cf(context['attached_service'], context['lvl1'])
            context['custom_fields'] = json.loads(context['lvl1'].custom_fields)
        except json.decoder.JSONDecodeError:
            context['custom_fields'] = {}
        except ObjectDoesNotExist:
            context['custom_fields'] = {}

        context['breeder'] = False
        if Breeder.objects.filter(account=context['attached_service'], user=self.request.user).exists():
            context['breeder'] = True

        context = generate_hirearchy(context)

        # stripe payment state
        if context['lvl1'].stripe_payment_token and context['attached_service'].pedigree_charging:
            context['payment_session'] = get_pedigree_payment_session(self.request, context['lvl1'])

        return context


class ShowPedigree(PedigreeBase):
    template_name = 'pedigree.html'

    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # check permission
        # get breeder_users of pedigree
        breeder_users = []
        pedigree = context['lvl1']
        if pedigree.breeder:
            if pedigree.breeder.user:
                breeder_users.append(pedigree.breeder.user)
        if pedigree.current_owner:
            if pedigree.current_owner.user:
                breeder_users.append(pedigree.current_owner.user)
        if self.request.method == 'GET':
            if not has_permission(self.request,
                                  {'read_only': 'breeder', 'contrib': True, 'admin': True, 'breed_admin': 'breed'},
                                  pedigrees=[pedigree],
                                  breeder_users=breeder_users):
                return redirect_2_login(self.request)
        else:
            raise PermissionDenied()
        
        return context


def render_to_pdf(template_src, context_dict):
    template = get_template(template_src)
    html = template.render(context_dict)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    return None


class GenerateCert(View):
    def dispatch(self, request, *args, **kwargs):
        # check permission
        if self.request.method == 'GET':
            pedigree = Pedigree.objects.get(id=self.kwargs['pedigree_id'])
            # get breeder_users of pedigree
            breeder_users = []
            if pedigree.breeder:
                if pedigree.breeder.user:
                    breeder_users.append(pedigree.breeder.user)
            if pedigree.current_owner:
                if pedigree.current_owner.user:
                    breeder_users.append(pedigree.current_owner.user)
            if not has_permission(self.request, {'read_only': 'breeder', 'contrib': 'breeder', 'admin': True, 'breed_admin': 'breed'},
                                        pedigrees=[pedigree],
                                        breeder_users=breeder_users):
                return redirect_2_login(self.request)
        else:
            raise PermissionDenied()
        
        return super().dispatch(request, *args, **kwargs)
    
    # certificate
    def get(self, request, *args, **kwargs):
        context = {}
        context['attached_service'] = get_main_account(request.user)
        context['lvl1'] = Pedigree.objects.exclude(state=States.UNAPPROVED).get(account=context['attached_service'], id=self.kwargs['pedigree_id'])

        # get account custom fields
        try:
            context['acc_custom_fields'] = json.loads(context['attached_service'].custom_fields)
        except json.decoder.JSONDecodeError:
            context['acc_custom_fields'] = {}
        # get pedigree custom fields
        try:
            context['ped_custom_fields'] = json.loads(context['lvl1'].custom_fields)
        except json.decoder.JSONDecodeError:
            context['ped_custom_fields'] = {}
        # get breeder custom fields
        try:
            context['breeder_custom_fields'] = json.loads(context['lvl1'].breeder.custom_fields)
        except json.decoder.JSONDecodeError:
            context['breeder_custom_fields'] = {}
        # get breed custom fields
        try:
            context['breed_custom_fields'] = json.loads(context['lvl1'].breed.custom_fields)
        except json.decoder.JSONDecodeError:
            context['breed_custom_fields'] = {}

        context = generate_hirearchy(context)

        if kwargs['type'] == 'cert':
            pdf_filename = "{date}-{name}{pedigree}-certificate".format(
                date=context['lvl1'].date_added.strftime('%Y-%m-%d'),
                name=slugify(context['lvl1'].name),
                pedigree=context['lvl1'].reg_no,
            )
            pdf = render_to_pdf('certificate.html', context)
        elif kwargs['type'] == 'zootech':
            pdf_filename = "{date}-{name}{pedigree}-zootechnical-certificate".format(
                date=context['lvl1'].date_added.strftime('%Y-%m-%d'),
                name=slugify(context['lvl1'].name),
                pedigree=context['lvl1'].reg_no,
            )
            pdf = render_to_pdf('cert-zootechnical.html', context)
            
        if pdf:
            response = HttpResponse(pdf, content_type='application/pdf')
            filename = "%s.pdf" % pdf_filename
            content = "attachment; filename=%s" % filename
            download = request.GET.get("download")
            if download:
                content = "attachment; filename=%s" % filename
            response['Content-Disposition'] = content
            return response
        return HttpResponse("Not found")


def get_parents(child, account):
    father, mother = '', ''
    
    # if child is a pedigree
    if type(child) == Pedigree:
        # if child has a father
        if child.parent_father:
            #set father
            try:
                father = Pedigree.objects.exclude(state=States.UNAPPROVED).get(account=account, reg_no=child.parent_father)
            except Pedigree.DoesNotExist:
                pass
        # if child has a mother, it wasn't born from a breed group
        if child.parent_mother:
            # set mother
            try:
                mother = Pedigree.objects.exclude(state=States.UNAPPROVED).get(account=account, reg_no=child.parent_mother)
            except Pedigree.DoesNotExist:
                pass
        # if born from a breed group
        elif child.breed_group:
            # set breed group as mother
            try:
                mother = BreedGroup.objects.get(account=account, group_name=child.breed_group)
            except BreedGroup.DoesNotExist:
                pass
            # set male of breed group as father
            if mother:
                if mother.group_members:
                    for member in mother.group_members.all():
                        if member.sex == PedigreeSex.MALE:
                            father = member
                            break
    # if child is a breed group
    elif type(child) == BreedGroup:
        # get mothers and fathers and parent breed groups of the females of the group
        groups = []
        mothers = []
        fathers = []
        if child.group_members:
            for member in child.group_members.all():
                # append mother and/or father to list if mothers and/or fathers
                if member.sex == PedigreeSex.FEMALE:
                    if member.breed_group not in groups:
                        groups.append(member.breed_group)
                    if member.parent_mother not in mothers:
                        mothers.append(member.parent_mother)
                    if member.parent_father not in fathers:
                        fathers.append(member.parent_father)
        # if all parent groups are the same
        if len(groups) == 1:
            # if all groups exist
            if groups[0]:
                # set group as mother
                try:
                    mother = BreedGroup.objects.get(account=account, group_name=groups[0])
                except BreedGroup.DoesNotExist:
                    pass
                # set male of group as father
                if mother.group_members:
                    for member in mother.group_members.all():
                        if member.sex == PedigreeSex.MALE:
                            father = member
                            break
                # set male of group as father
        # if all mothers are the same
        if len(mothers) == 1:
            # if all mothers exist
            if mothers[0]:
                # set mother
                try:
                    mother = Pedigree.objects.exclude(state=States.UNAPPROVED).get(account=account, reg_no=mothers[0])
                except Pedigree.DoesNotExist:
                    pass
        # if all fathers are the same
        if len(fathers) == 1:
            # if all fathers exist
            if fathers[0]:
                # set father
                try:
                    father = Pedigree.objects.exclude(state=States.UNAPPROVED).get(account=account, reg_no=fathers[0])
                except Pedigree.DoesNotExist:
                    pass
    return father, mother


def generate_hirearchy(context):
    # lvl 2 (2_1 and 2_2)
    father, mother = get_parents(context['lvl1'], context['attached_service'])
    context['lvl2_1'] = father
    if type(mother) == BreedGroup:
        context['lvl2_2_grp'] = mother
    else:
        context['lvl2_2'] = mother

    # lvl 3 (3_1 and 3_2)
    father, mother = get_parents(context['lvl2_1'], context['attached_service'])
    context['lvl3_1'] = father
    if type(mother) == BreedGroup:
        context['lvl3_2_grp'] = mother
    else:
        context['lvl3_2'] = mother

    # lvl 3 (3_3 and 3_4)
    if 'lvl2_2' in context.keys():
        father, mother = get_parents(context['lvl2_2'], context['attached_service'])
    elif 'lvl2_2_grp' in context.keys():
        father, mother = get_parents(context['lvl2_2_grp'], context['attached_service'])
    context['lvl3_3'] = father
    if type(mother) == BreedGroup:
        context['lvl3_4_grp'] = mother
    else:
        context['lvl3_4'] = mother

    # lvl 4 (4_1 and 4_2)
    father, mother = get_parents(context['lvl3_1'], context['attached_service'])
    context['lvl4_1'] = father
    if type(mother) == BreedGroup:
        context['lvl4_2_grp'] = mother
    else:
        context['lvl4_2'] = mother

    # lvl 4 (4_3 and 4_4)
    if 'lvl3_2' in context.keys():
        father, mother = get_parents(context['lvl3_2'], context['attached_service'])
    elif 'lvl3_2_grp' in context.keys():
        father, mother = get_parents(context['lvl3_2_grp'], context['attached_service'])
    context['lvl4_3'] = father
    if type(mother) == BreedGroup:
        context['lvl4_4_grp'] = mother
    else:
        context['lvl4_4'] = mother

    # lvl 4 (4_5 and 4_6)
    father, mother = get_parents(context['lvl3_3'], context['attached_service'])
    context['lvl4_5'] = father
    if type(mother) == BreedGroup:
        context['lvl4_6_grp'] = mother
    else:
        context['lvl4_6'] = mother

    # lvl 4 (4_7 and 4_8)
    if 'lvl3_4' in context.keys():
        father, mother = get_parents(context['lvl3_4'], context['attached_service'])
    elif 'lvl3_4_grp' in context.keys():
        father, mother = get_parents(context['lvl3_4_grp'], context['attached_service'])
    context['lvl4_7'] = father
    if type(mother) == BreedGroup:
        context['lvl4_8_grp'] = mother
    else:
        context['lvl4_8'] = mother
    
    return context


@login_required(login_url="/account/login")
@never_cache
def new_pedigree_form(request):
    pedigree_form = PedigreeForm(request.POST or None, request.FILES or None)
    pre_checks = True
    attached_service = get_main_account(request.user)
    
    # check if user has permission, passing in ids of mother and father from kinship queue item
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        # (particular breed checked below)
        # specify breeder to validate user is breeder
        if Breeder.objects.filter(account=attached_service, breeding_prefix=pedigree_form['breeder'].value()).exists():
            if not has_permission(request, {'read_only': False, 'contrib': 'breeder', 'admin': True, 'breed_admin': True},
                                            breeder_users=[Breeder.objects.get(account=attached_service, breeding_prefix=pedigree_form['breeder'].value()).user]):
                return HttpResponse(json.dumps({'result': 'fail', 'errors': {'field_errors': [],'non_field_errors': ['You do not have permission!']}}))
        # if breeder doesn't exist, allow contribs on through as that error will be handled later
        else:
            if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
                return HttpResponse(json.dumps({'result': 'fail', 'errors': {'field_errors': [],'non_field_errors': ['You do not have permission!']}}))
    else:
        raise PermissionDenied()
    
    try:
        custom_fields = json.loads(attached_service.custom_fields)
    except json.decoder.JSONDecodeError:
        custom_fields = {}

    if request.method == 'POST':
        # check whether it's valid:
        if Pedigree.objects.filter(reg_no=pedigree_form['reg_no'].value().strip()).exists():
            pedigree_form.add_error('reg_no', 'Selected reg number already exists.')
            pre_checks = False
        if not Breeder.objects.filter(account=attached_service, breeding_prefix=pedigree_form['breeder'].value()).exists() and pedigree_form['breeder'].value() not in ['Breeder', '', 'None', None]:
            pedigree_form.add_error('breeder', 'Selected breeder does not exist.')
            pre_checks = False
        if not Breeder.objects.filter(account=attached_service, breeding_prefix=pedigree_form['current_owner'].value()).exists() and pedigree_form['current_owner'].value() not in ['Current Owner', '', 'None', None]:
            pedigree_form.add_error('current_owner', 'Selected owner does not exist.')
            pre_checks = False
        try:
            if not Pedigree.objects.filter(account=attached_service, reg_no=pedigree_form['mother'].value().strip()).exists() and pedigree_form['mother'].value().strip() not in ['Mother', '', 'None', None]:
                pedigree_form.add_error('mother', 'Selected mother does not exist.')
                pre_checks = False
        except AttributeError:
            # ends up here if a breed group is added, so pedigree_form['mother'] doesn't exist in the post request
            pass
        if not Pedigree.objects.filter(account=attached_service, reg_no=pedigree_form['father'].value().strip()).exists() and pedigree_form['father'].value() not in ['Father', '', 'None', None]:
            pedigree_form.add_error('father', 'Selected father does not exist.')
            pre_checks = False
        if not BreedGroup.objects.filter(account=attached_service, group_name=pedigree_form['breed_group'].value()).exists() and pedigree_form['breed_group'].value() not in ['Group pedigree was born from', '', 'None', None]:
            pedigree_form.add_error('breed_group', 'Selected breed group does not exist.')
            pre_checks = False
        if not Breed.objects.filter(account=attached_service, breed_name=pedigree_form['breed'].value()).exists() and pedigree_form['breed'].value() not in ['Breed', '', 'None', None]:
            pedigree_form.add_error('breed', 'Selected breed does not exist.')
            pre_checks = False
        # get breeds editable (length is 0 if they're not a breed admin)
        breeds_editable = request.POST.get('breeds-editable').replace('[', '').replace(']', '').replace("&#39;", '').replace("'", '').replace(', ', ',').split(',')
        if '' in breeds_editable:
            breeds_editable.remove('')
        if len(breeds_editable) > 0 and pedigree_form['breed'].value() not in breeds_editable:
            pedigree_form.add_error('breed', 'You are not an editor for the selected breed.')
            pre_checks = False
        if pedigree_form.is_valid() and pre_checks:
            new_pedigree = Pedigree()
            new_pedigree.creator = request.user
            try:
                new_pedigree.breeder = Breeder.objects.get(account=attached_service, breeding_prefix=pedigree_form['breeder'].value())
            except ObjectDoesNotExist:
                pass
            try:
                new_pedigree.current_owner = Breeder.objects.get(account=attached_service, breeding_prefix=pedigree_form['current_owner'].value())
            except ObjectDoesNotExist:
                pass
            new_pedigree.reg_no = pedigree_form['reg_no'].value().strip()
            new_pedigree.tag_no = pedigree_form['tag_no'].value().strip()
            new_pedigree.name = pedigree_form['name'].value()
            try:
                new_pedigree.date_of_registration = pedigree_form['date_of_registration'].value() or None
            except:
                pass
            try:
                new_pedigree.dob = pedigree_form['date_of_birth'].value() or None
            except:
                pass
            new_pedigree.status = pedigree_form['status'].value()
            new_pedigree.sex = pedigree_form['sex'].value()
            new_pedigree.litter_size = pedigree_form['litter_size'].value()
            try:
                new_pedigree.dod = pedigree_form['date_of_death'].value() or None
            except:
                pass

            ### mother ###
            try:
                new_pedigree.parent_mother = Pedigree.objects.get(account=attached_service, reg_no=pedigree_form['mother'].value().strip())

            except (ObjectDoesNotExist, AttributeError):
                new_pedigree.breed_group = pedigree_form['breed_group'].value()

            try:
                new_pedigree.parent_mother_notes = pedigree_form['mother_notes'].value() or ''
            except:
                pass

            ### father ###
            try:
                new_pedigree.parent_father = Pedigree.objects.get(account=attached_service, reg_no=pedigree_form['father'].value().strip())
            except ObjectDoesNotExist:
                pass
            try:
                new_pedigree.parent_father_notes = pedigree_form['father_notes'].value() or ''
            except:
                pass

            new_pedigree.description = pedigree_form['description'].value()
            new_pedigree.account = attached_service

            breed = Breed.objects.get(account=attached_service, breed_name=request.POST.get('breed'))
            new_pedigree.breed = breed

            # sale or hire
            new_pedigree.sale_or_hire = pedigree_form['sale_or_hire'].value()

            try:
                custom_fields = json.loads(attached_service.custom_fields)

                for id, field in custom_fields.items():
                    custom_fields[id]['field_value'] = request.POST.get(custom_fields[id]['fieldName'])
            except json.decoder.JSONDecodeError:
                pass

            new_pedigree.custom_fields = json.dumps(custom_fields)

            if request.user in attached_service.contributors.all():
                new_pedigree.state = 'unapproved'
                new_pedigree.save()
                create_approval(request, new_pedigree, attached_service, state=States.UNAPPROVED, type='new')

            else:
                new_pedigree.save()

            # redirect for charging
            if attached_service.pedigree_charging and request.user in attached_service.contributors.all():
                #session_url = pedigree_charging_session(request, new_pedigree, pedigree_form['registration_charge'].value())
                session_url = f'/pedigree/pedigree_checkout/{new_pedigree.id}/{pedigree_form["registration_charge"].value()}'
                
                return HttpResponse(json.dumps({'result': 'payment_redirect', 'url': session_url}))
            else:
                new_pedigree.paid = True
                new_pedigree.save()

            return HttpResponse(json.dumps({'result': 'success', 'ped_id': new_pedigree.id}))
        # form invalid
        else:
            # variable to store form errors to be passed to template
            errors = {}
            if pedigree_form.errors:
                errors['field_errors'] = []
                errors['non_field_errors'] = []
                
                for field in pedigree_form:
                    for error in field.errors:
                        # add field label and error to dictionary
                        errors['field_errors'].append({
                            'field': field.label,
                            'error': error
                        })

                for non_field_error in pedigree_form.non_field_errors():
                    errors['non_field_errors'].append(non_field_error)
            
            return HttpResponse(json.dumps({'result': 'fail', 'errors': errors}))
    else:
        pedigree_form = PedigreeForm()

    suggested_reg = get_next_reg(attached_service)

    mother_reg = ''
    father_reg= ''
    if request.GET.get('parent'):
        parent = Pedigree.objects.filter(account=attached_service, id=request.GET.get('parent'))
        if parent.exists():
            parent = parent.first()
            if parent.sex == PedigreeSex.FEMALE:
                mother_reg = parent.reg_no
            elif parent.sex == PedigreeSex.MALE:
                father_reg = parent.reg_no

    # pedigree charging
    prices = None
    if attached_service.pedigree_charging:
        from .pedigree_charging import get_pedigree_prices
        prices = get_pedigree_prices(request, attached_service)

    return render(request, 'new_pedigree_form_base.html', {'pedigree_form': pedigree_form,
                                                           'pedigrees': Pedigree.objects.filter(account=attached_service),
                                                           'breeds': Breed.objects.filter(account=attached_service),
                                                           'breed_groups': BreedGroup.objects.filter(account=attached_service),
                                                           'custom_fields': custom_fields,
                                                           'breeder_form': BreederForm(),
                                                           'breed_form': BreedForm(),
                                                           'suggested_reg': suggested_reg,
                                                           'mother_reg': mother_reg,
                                                           'father_reg': father_reg,
                                                           'prices': prices})


@login_required(login_url="/account/login")
@never_cache
def edit_pedigree_form(request, id):
    attached_service = get_main_account(request.user)
    pedigree = Pedigree.objects.get(account=attached_service, id__exact=int(id))

    # check if user has permission
    # get breeder users
    breeder_users = []
    if pedigree.current_owner:
        if pedigree.current_owner.user:
            breeder_users.append(pedigree.current_owner.user)
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': 'breeder', 'admin': True, 'breed_admin': 'breed'}, pedigrees=[pedigree],
                                        breeder_users=breeder_users):
            return redirect_2_login(request)
    elif request.method == 'POST':
        # particular breed checked below
        if not has_permission(request, {'read_only': False, 'contrib': 'breeder', 'admin': True, 'breed_admin': 'breed'}, pedigrees=[pedigree],
                                        breeder_users=breeder_users):
            return HttpResponse(json.dumps({'result': 'fail', 'errors': {'field_errors': [],'non_field_errors': ['You do not have permission!']}}))
    else:
        raise PermissionDenied()

    # if state is edited make sure to show edited information
    if pedigree.state == States.EDITED:
        approval = Approval.objects.get(pedigree=pedigree)
        for obj in serializers.deserialize("yaml", approval.data):
            obj.object.state = 'edited'
            pedigree = obj.object

    pedigree_form = PedigreeForm(request.POST or None, request.FILES or None)
    image_form = ImagesForm(request.POST or None, request.FILES or None)
    pre_checks = True

    try:
        # get custom fields
        custom_fields = json.loads(pedigree.custom_fields)
    except json.decoder.JSONDecodeError:
        try:
            # get custom fields template
            custom_fields = json.loads(attached_service.custom_fields)
            Pedigree.objects.filter(id=pedigree.id).update(custom_fields=json.dumps(custom_fields))
        except json.decoder.JSONDecodeError:
            custom_fields = {}
    except ObjectDoesNotExist:
        custom_fields = {}

    if request.method == 'POST':
        if 'delete' in request.POST:
            if request.user in attached_service.contributors.all():
                # contributors are not allowed to delete pedigrees!
                pass
            else:
                pedigree.delete()
                # delete any existed approvals
                approvals = Approval.objects.filter(pedigree=pedigree)
                for approval in approvals:
                    approval.delete()
            return HttpResponse()

        # check whether it's valid:
        if pedigree_form['reg_no'].value().strip() != pedigree.reg_no:
            if Pedigree.objects.filter(reg_no=pedigree_form['reg_no'].value().strip()).exists():
                pedigree_form.add_error('reg_no', 'Selected reg number already exists.')
                pre_checks = False
        if not Breeder.objects.filter(account=attached_service, breeding_prefix=pedigree_form['breeder'].value().strip()).exists() and pedigree_form['breeder'].value() not in ['Breeder', '', 'None', None]:
            pedigree_form.add_error('breeder', 'Selected breeder does not exist.')
            pre_checks = False
        if not Breeder.objects.filter(account=attached_service, breeding_prefix=pedigree_form['current_owner'].value().strip()).exists() and pedigree_form['current_owner'].value() not in ['Current Owner', '', 'None', None]:
            pedigree_form.add_error('current_owner', 'Selected owner does not exist.')
            pre_checks = False
        try:
            if not Pedigree.objects.filter(account=attached_service, reg_no=pedigree_form['mother'].value().strip()).exists() and pedigree_form['mother'].value() not in ['Mother', '', 'None', None]:
                pedigree_form.add_error('mother', 'Selected mother does not exist.')
                pre_checks = False
        except AttributeError:
            # ends up here if a breed group is added, so pedigree_form['mother'] doesn't exist in the post request
            pass
        if not Pedigree.objects.filter(account=attached_service, reg_no=pedigree_form['father'].value().strip()).exists() and pedigree_form['father'].value() not in ['Father', '', 'None', None]:
            pedigree_form.add_error('father', 'Selected father does not exist.')
            pre_checks = False
        if not BreedGroup.objects.filter(account=attached_service, group_name=pedigree_form['breed_group'].value()).exists() and pedigree_form['breed_group'].value() not in ['Group pedigree was born from', '', 'None', None]:
            pedigree_form.add_error('breed_group', 'Selected breed group does not exist.')
            pre_checks = False
        if not Breed.objects.filter(account=attached_service, breed_name=pedigree_form['breed'].value()).exists() and pedigree_form['breed'].value() not in ['Breed', '', 'None', None]:
            pedigree_form.add_error('breed', 'Selected breed does not exist.')
            pre_checks = False

        if pedigree_form.is_valid() and image_form.is_valid() and pre_checks:
            try:
                if pedigree_form['breeder'].value() == '':
                    pedigree.breeder = None
                else:
                    pedigree.breeder = Breeder.objects.get(account=attached_service, breeding_prefix=pedigree_form['breeder'].value())
            except ObjectDoesNotExist:
                pedigree.breeder = None

            try:
                if pedigree_form['current_owner'] == '':
                    pedigree.current_owner = None
                else:
                    pedigree.current_owner = Breeder.objects.get(account=attached_service, breeding_prefix=pedigree_form['current_owner'].value())
            except ObjectDoesNotExist:
                pass

            pedigree.reg_no = pedigree_form['reg_no'].value().strip()
            pedigree.tag_no = pedigree_form['tag_no'].value().strip() or ""
            pedigree.name = pedigree_form['name'].value()

            try:
                pedigree.date_of_registration = pedigree_form['date_of_registration'].value() or None
            except:
                pass

            try:
                pedigree.dob = pedigree_form['date_of_birth'].value() or None
            except:
                pass
            pedigree.status = pedigree_form['status'].value()
            pedigree.sex = pedigree_form['sex'].value()
            pedigree.litter_size = pedigree_form['litter_size'].value()

            try:
                pedigree.dod = pedigree_form['date_of_death'].value() or None
            except:
                pass

            try:
                if pedigree_form['mother'].value() in ('', None):
                    pedigree.parent_mother = None
                else:
                    try:
                        pedigree.parent_mother = Pedigree.objects.get(account=attached_service, reg_no=pedigree_form['mother'].value().strip())
                    except (ObjectDoesNotExist, AttributeError):
                        pedigree.breed_group = pedigree_form['breed_group'].value()

            except:
                pass

            try:
                pedigree.parent_mother_notes = pedigree_form['mother_notes'].value() or ''
            except:
                pass

            try:
                if pedigree_form['father'].value() in ('', None):
                    pedigree.parent_father = None
                else:
                    pedigree.parent_father = Pedigree.objects.get(account=attached_service, reg_no=pedigree_form['father'].value().strip())
            except ObjectDoesNotExist:
                pass
            try:
                pedigree.parent_father_notes = pedigree_form['father_notes'].value() or ''
            except:
                pass

            try:
                pedigree.breed_group = pedigree_form['breed_group'].value()
            except:
                pass

            pedigree.description = pedigree_form['description'].value()

            pedigree.breed = Breed.objects.get(account=attached_service, breed_name=pedigree_form['breed'].value())

            pedigree.sale_or_hire = pedigree_form['sale_or_hire'].value()

            try:
                custom_fields = json.loads(pedigree.custom_fields)
            except json.decoder.JSONDecodeError:
                custom_fields = {}
            for id, field in custom_fields.items():
                custom_fields[id]['field_value'] = request.POST.get(custom_fields[id]['fieldName'])

            pedigree.custom_fields = json.dumps(custom_fields)

            if request.user in attached_service.contributors.all():
                if not Approval.objects.filter(pedigree=pedigree).exists():
                    create_approval(request, pedigree, attached_service, state=States.EDITED, type='edit')
            else:
                # delete any existed approvals
                approvals = Approval.objects.filter(pedigree=pedigree)
                for approval in approvals:
                    approval.delete()
                pedigree.state = 'approved'
                pedigree.save()

            for image in PedigreeImage.objects.filter(account=attached_service):
                img = request.POST.get('{}-{}'.format(pedigree.id, image.id))
                if img:
                    if request.user in attached_service.contributors.all():
                        image.state = 'edited'
                        image.save()
                    else:
                        image.delete()

            return HttpResponse(json.dumps({'result': 'success'}))
        # form invalid
        else:
            # variable to store form errors to be passed to template
            errors = {}
            if pedigree_form.errors:
                errors['field_errors'] = []
                errors['non_field_errors'] = []
                
                for field in pedigree_form:
                    for error in field.errors:
                        # add field label and error to dictionary
                        errors['field_errors'].append({
                            'field': field.label,
                            'error': error
                        })

                for non_field_error in pedigree_form.non_field_errors():
                    errors['non_field_errors'].append(non_field_error)
            
            return HttpResponse(json.dumps({'result': 'fail', 'errors': errors}))
    else:
        pedigree_form = PedigreeForm()

    return render(request, 'edit_pedigree_form.html', {'pedigree_form': pedigree_form,
                                                       'image_form': image_form,
                                                       'pedigree': pedigree,
                                                       'pedigrees': Pedigree.objects.filter(account=attached_service),
                                                       'breeders': Breeder.objects.filter(account=attached_service),
                                                       'breeds': Breed.objects.filter(account=attached_service),
                                                       'breed_groups': BreedGroup.objects.filter(account=attached_service),
                                                       'custom_fields': custom_fields})


def image_upload(request, id):
    attached_service = get_main_account(request.user)
    pedigree = Pedigree.objects.get(account=attached_service, id__exact=int(id))

    image = request.FILES['file[0]']
    from PIL import Image
    #from PIL.Image import core as _imaging
    from django.core.files.base import ContentFile
    import pyheif
    from io import BytesIO
    from os import path

    filename, file_extension = path.splitext(str(request.FILES['file[0]']))
    if file_extension.upper() == ".HEIC":
        img_io = BytesIO()
        heif_file = pyheif.read(request.FILES['file[0]'])
        image = Image.frombytes(mode=heif_file.mode, size=heif_file.size, data=heif_file.data)
        image.save(img_io, format='JPEG', quality=100)
        image = ContentFile(img_io.getvalue(), f"{filename}.jpeg")

    if request.user in attached_service.contributors.all():
        upload = PedigreeImage(account=attached_service, state=States.UNAPPROVED, image=image, reg_no=pedigree)
        upload.save()
    else:
        upload = PedigreeImage(account=attached_service, image=image, reg_no=pedigree)
        upload.save()
    return HttpResponse('')


def add_existing(request, pedigree_id):
    attached_service = get_main_account(request.user)
    pedigree = Pedigree.objects.get(account=attached_service, id=pedigree_id)

    # check if user has permission (should just be post)
    breeder_users = []
    if pedigree.current_owner:
        if pedigree.current_owner.user:
            breeder_users.append(pedigree.current_owner.user)
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': 'breed', 'admin': True, 'breed_admin': 'breed'}, 
                                        pedigrees=[pedigree],
                                        breeder_users=breeder_users):
            return HttpResponse(json.dumps({'fail': True, 'msg': 'You do not have permission!'}))
    else:
        raise PermissionDenied()

    child_reg = request.POST.get('reg_no')
    child = Pedigree.objects.filter(account=attached_service, reg_no=child_reg)

    # check parent exists
    if child.exists():
        child = child.first()
    else:
        return HttpResponse(json.dumps({'fail': True, 'msg': 'Input child does not exist!'}))

    # check breed is correct
    if child.breed.id != int(request.POST.get('breed')):
        return HttpResponse(json.dumps({'fail': True, 'msg': f'Input child is not a {pedigree.breed.breed_name}!'}))

    if pedigree.sex == PedigreeSex.MALE:
        child.parent_father = pedigree
    elif pedigree.sex == PedigreeSex.FEMALE:
        child.parent_mother = pedigree

    if request.user in attached_service.contributors.all():
        create_approval(request, child, attached_service, state=States.EDITED, type='edit')
    else:
        child.save()

    return HttpResponse(json.dumps({'success': True}))


def add_existing_parent(request, pedigree_id):
    attached_service = get_main_account(request.user)
    pedigree = Pedigree.objects.get(account=attached_service, id=pedigree_id)

    # check if user has permission (should just be post)
    breeder_users = []
    if pedigree.breeder:
        if pedigree.breeder.user:
            breeder_users.append(pedigree.breeder.user)
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': False, 'contrib': 'breeder', 'admin': True, 'breed_admin': 'breed'}, 
                                        pedigrees=[pedigree],
                                        breeder_users=breeder_users):
            return HttpResponse(json.dumps({'fail': True, 'msg': 'You do not have permission!'}))
    else:
        raise PermissionDenied()

    parent_reg = request.POST.get('reg_no')
    parent = Pedigree.objects.filter(account=attached_service, reg_no=parent_reg)

    # check parent exists
    if parent.exists():
        parent = parent.first()
    else:
        return HttpResponse(json.dumps({'fail': True, 'msg': 'Input parent does not exist!'}))

    # check breed is correct
    if parent.breed.id != int(request.POST.get('breed')):
        return HttpResponse(json.dumps({'fail': True, 'msg': f'Input parent is not a {pedigree.breed.breed_name}!'}))

    if parent.sex == PedigreeSex.MALE:
        pedigree.parent_father = parent
    elif parent.sex == PedigreeSex.FEMALE:
        pedigree.parent_mother = parent

    if request.user in attached_service.contributors.all():
        create_approval(request, pedigree, attached_service, state=States.EDITED, type='edit')
    else:
        pedigree.save()

    return HttpResponse(json.dumps({'success': True}))


@login_required(login_url="/account/login")
def pedigree_checkout(request, id, price):
    # id = pedigree DB ID
    pedigree = Pedigree.objects.get(id=id)
    stripe_account = StripeAccount.objects.get(account=pedigree.account)
    return render(request, 'pedigree_checkout.html', {'pedigree': pedigree,
                                                      'price': price,
                                                      'stripe_pk': get_stripe_public_key(request),
                                                      'connect_account_id': stripe_account.stripe_acct_id})


def create_approval(request, pedigree, attached_service, state, type):
    if state == States.EDITED:
        Pedigree.objects.filter(id=pedigree.id).update(state=state)
    elif state == 'unapproved':
        Pedigree.objects.filter(id=pedigree.id).update(state=state)

    try:
        pedigree.dob = dateutil.parser.parse(pedigree.dob)
    except TypeError:
        pass
    try:
        pedigree.dod = dateutil.parser.parse(pedigree.dod)
    except TypeError:
        pass
    try:
        pedigree.date_of_registration = dateutil.parser.parse(pedigree.date_of_registration)
    except TypeError:
        pass
    data = serializers.serialize('yaml', [pedigree])
    Approval.objects.create(account=attached_service,
                            user=request.user,
                            type=type,
                            pedigree=pedigree,
                            data=data)


@login_required(login_url="/account/login")
@never_cache
def get_pedigree_details(request):
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        return redirect_2_login(request)
    attached_service = get_main_account(request.user)
    
    # get the pedigree that was input
    try:
        pedigree = Pedigree.objects.get(account=attached_service, reg_no=request.GET['id'])
    except Pedigree.DoesNotExist:
        return HttpResponse(json.dumps({'result': 'fail'}))
    except MultiValueDictKeyError:
        return HttpResponse(json.dumps({'result': 'fail'}))
    
    # if this was called from edit form and parent given is the same as pedigree being editted, return fail
    if request.GET.get('form_type') and request.GET.get('pedigree'):
        if request.GET['form_type'] in ('edit', 'view'):
            if pedigree.reg_no == request.GET['pedigree']:
                return HttpResponse(json.dumps({'result': 'fail'}))

    # if the input field is a mother/father field, return fail if the input pedigree is the wrong sex
    if request.GET.get('parent_type'):
        if (request.GET['parent_type'] == 'father' and pedigree.sex != PedigreeSex.MALE) or (request.GET['parent_type'] == 'mother' and pedigree.sex != PedigreeSex.FEMALE):
            return HttpResponse(json.dumps({'result': 'fail'}))

    # if the input field required pedigree to be alive, return fail if the input pedigree is not alive
    if request.GET.get('status'):
        if (request.GET['status'] == PedigreeStatus.ALIVE and pedigree.status != PedigreeStatus.ALIVE):
            return HttpResponse(json.dumps({'result': 'fail'}))

    # if the input field required the pedigree to be of a certain breed, return fail if the breed is incorrect
    if request.GET.get('breed'):
        if pedigree.breed.breed_name != request.GET.get('breed'):
            return HttpResponse(json.dumps({'result': 'fail'}))
    
    pedigree = serializers.serialize('json', [pedigree], ensure_ascii=False)
    return HttpResponse(json.dumps({'result': 'success',
                                    'pedigree': pedigree}))


def update_pedigree_cf(attached_service, pedigree):
    # check custom fields are correct
    try:
        ped_custom_fields = json.loads(pedigree.custom_fields)
    except json.decoder.JSONDecodeError:
        ped_custom_fields = {}
    try:
        acc_custom_fields = json.loads(attached_service.custom_fields)
    except json.decoder.JSONDecodeError:
        acc_custom_fields = {}

    # variable to keep track of whether the field has been updated
    changed = False

    # go through account custom fields
    for key, val in acc_custom_fields.items():
        # add the field to pedigree custom fields if not already there
        if key not in ped_custom_fields.keys():
            ped_custom_fields[key] = {'id': val['id'],
                                    'location': val['location'],
                                    'fieldName': val['fieldName'],
                                    'fieldType': val['fieldType']}
            changed = True
        # update custom fields if they have been edited
        else:
            if ped_custom_fields[key]['id'] != val['id']:
                ped_custom_fields[key]['id'] = val['id']
                changed = True
            if ped_custom_fields[key]['location'] != val['location']:
                ped_custom_fields[key]['location'] = val['location']
                changed = True
            if ped_custom_fields[key]['fieldName'] != val['fieldName']:
                ped_custom_fields[key]['fieldName'] = val['fieldName']
                changed = True
            if ped_custom_fields[key]['fieldType'] != val['fieldType']:
                ped_custom_fields[key]['fieldType'] = val['fieldType']
                changed = True

    # go through pedigree custom fields
    to_delete = []
    for key, val in ped_custom_fields.items():
        # remove custom field if it has been deleted from account
        if key not in acc_custom_fields.keys():
            to_delete.append(key)
            changed = True
    for key in to_delete:
        ped_custom_fields.pop(key, None)
    
    # update pedigree custom fields if we need to
    if changed:
        pedigree.custom_fields = json.dumps(ped_custom_fields)
        pedigree.save()
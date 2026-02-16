from django.shortcuts import render, redirect, HttpResponse, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core import serializers
from django.core.exceptions import PermissionDenied
from .models import BreedGroup
from pedigree.models import Pedigree
from breeder.models import Breeder
from breed.models import Breed
from account.views import is_editor, get_main_account, has_permission, redirect_2_login
from .forms import BreedGroupForm
from approvals.models import Approval
from cloudlines.constants import States
import re
from json import dumps


@login_required(login_url="/account/login")
def breed_groups(request):
    attached_service = get_main_account(request.user)
    return render(request, 'breed_groups.html', {'groups': BreedGroup.objects.filter(account=attached_service)})


@login_required(login_url="/account/login")
def new_breed_group_form(request):
    breed_group_form = BreedGroupForm(request.POST or None, request.FILES or None)
    attached_service = get_main_account(request.user)
    
    # check if user has permission
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        # specify breeder to validate user is breeder
        if Breeder.objects.filter(account=attached_service, breeding_prefix=breed_group_form['breeder'].value()).exists():
            if not has_permission(request, {'read_only': False, 'contrib': 'breeder', 'admin': True, 'breed_admin': True},
                                            breeder_users=[Breeder.objects.get(account=attached_service, breeding_prefix=breed_group_form['breeder'].value()).user]):
                return HttpResponse(dumps({'result': 'fail', 'msg': 'You do not have permission!'}))
        # if breeder doesn't exist, allow contribs on through
        else:
            if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
                return HttpResponse(dumps({'result': 'fail', 'msg': 'You do not have permission!'}))
    else:
        raise PermissionDenied()
    
    if request.method == 'POST':
        # validate that input is given
        if breed_group_form['breeder'].value() == '':
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Breeder was not given!'}))
        elif breed_group_form['breed'].value() == '--Select Breed--':
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Breed was not given!'}))
        elif breed_group_form['group_name'].value() == '':
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Group ID was not given!'}))
        elif not request.POST.get('member-0'):
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Group members were not given!'}))
        
        new_breed_group = BreedGroup()
        try:
            new_breed_group.breeder = Breeder.objects.get(account=attached_service, breeding_prefix=breed_group_form['breeder'].value())
        except Breeder.DoesNotExist:
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Breeder does not exist!'}))
        
        # variable to check that 1 male was given and at least 1 female was given
        male_count = 0
        female_count = 0
        
        # get the input members
        member_index = 0
        member_inputs = []
        while request.POST.get(f'member-{member_index}'):
            member_inputs.append(request.POST.get(f'member-{member_index}'))
            member_index += 1
        # create list of group members to be added after the breed group is saved
        group_members = []
        for id in member_inputs:
            # increment male_count if it's male, female_count if it's female
            if 'M | ' in id:
                male_count += 1
            if 'F | ' in id:
                female_count += 1
            
            id = id[4:]
            pedigree = Pedigree.objects.get(account=attached_service, reg_no=id)
            group_members.append(pedigree)

        # check number of males and females given is correct
        if male_count != 1:
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Number of males must be one!'}))
        if female_count < 1:
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Number of females must be at least one!'}))

        # check group ID is not taken
        if BreedGroup.objects.filter(account=attached_service, group_name=breed_group_form['group_name'].value()).exists():
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Group ID is already in use!'}))
        
        new_breed_group.breed = Breed.objects.get(account=attached_service, breed_name=breed_group_form['breed'].value())
        new_breed_group.group_name = breed_group_form['group_name'].value()
        new_breed_group.account = attached_service
        new_breed_group.save()

        # add group members to breed group
        for member in group_members:
            new_breed_group.group_members.add(member)

        if request.user in attached_service.contributors.all():
            new_breed_group.state = 'unapproved'
            new_breed_group.save()

            data = serializers.serialize('yaml', [new_breed_group])
            Approval.objects.create(account=attached_service,
                                    user=request.user,
                                    type='new',
                                    breed_group=new_breed_group,
                                    data=data)
        else:
            new_breed_group.save()

        return HttpResponse(dumps({"result": "success"}))

    else:
        breed_group_form = BreedGroupForm()

        # get next available group ID
        suggested_name = 'BG12345'
        try:
            latest_added = BreedGroup.objects.filter(account=attached_service).latest('group_name')
            latest_name = latest_added.group_name
            name_ints_re = re.search("[0-9]+", latest_name)
            suggested_name = latest_name.replace(str(name_ints_re.group(0)), str(int(name_ints_re.group(0))+1).zfill(len(name_ints_re.group(0))))
        except BreedGroup.DoesNotExist:
            pass
        except AttributeError:
            pass

    return render(request, 'new_breed_group_form.html', {'breed_group_form': breed_group_form,
                                                         'breeders': Breeder.objects.filter(account=attached_service),
                                                         'breeds': Breed.objects.filter(account=attached_service),
                                                         'suggested_name': suggested_name})


@login_required(login_url="/account/login")
def edit_breed_group_form(request, breed_group_name):
    breed_group = get_object_or_404(BreedGroup, id=breed_group_name)

    breed_group_form = BreedGroupForm(request.POST or None, request.FILES or None, instance=breed_group)
    attached_service = get_main_account(request.user)
    
    # check if user has permission, passing in ids of mother and father from kinship queue item
    if request.method == 'GET':
        if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
            return redirect_2_login(request)
    elif request.method == 'POST':
        # specify breeder to validate user is breeder
        if Breeder.objects.filter(account=attached_service, breeding_prefix=breed_group_form['breeder'].value()).exists():
            if not has_permission(request, {'read_only': False, 'contrib': 'breeder', 'admin': True, 'breed_admin': True},
                                            breeder_users=[Breeder.objects.get(account=attached_service, breeding_prefix=breed_group_form['breeder'].value()).user]):
                return HttpResponse(dumps({'result': 'fail', 'msg': 'You do not have permission!'}))
        # if breeder doesn't exist, allow contribs on through
        else:
            if not has_permission(request, {'read_only': False, 'contrib': True, 'admin': True, 'breed_admin': True}):
                return HttpResponse(dumps({'result': 'fail', 'msg': 'You do not have permission!'}))
    else:
        raise PermissionDenied()
    
    members = []
    if request.method == 'POST':
        if request.POST.get('delete'):
            if request.user in attached_service.contributors.all():
                # contributors are not allowed to delete pedigrees!
                pass
            else:
                breed_group.delete()
                # delete any existed approvals
                approvals = Approval.objects.filter(breed_group=breed_group)
                for approval in approvals:
                    approval.delete()
            return HttpResponse(dumps({"result": "success"}))
        
        # validate that input is given
        if breed_group_form['breeder'].value() == '':
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Breeder was not given!'}))
        elif breed_group_form['breed'].value() == '--Select Breed--':
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Breed was not given!'}))
        elif breed_group_form['group_name'].value() == '':
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Group ID was not given!'}))
        elif not request.POST.get('member-0'):
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Group members were not given!'}))
        
        try:
            breed_group.breeder = Breeder.objects.get(account=attached_service, breeding_prefix=breed_group_form['breeder'].value())
        except Breeder.DoesNotExist:
            return HttpResponse(dumps({'result': 'fail', 'msg': 'Breeder does not exist!'}))
        
        # if changed, check group_name hasn't been taken
        if breed_group.group_name != breed_group_form['group_name'].value():
            if BreedGroup.objects.filter(account=attached_service, group_name=breed_group_form['group_name'].value()).exists():
                return HttpResponse(dumps({'result': 'fail', 'msg': 'Group ID is already in use!'}))
        
        breed_group.breed = Breed.objects.get(account=attached_service, breed_name=breed_group_form['breed'].value())
        breed_group.group_name = breed_group_form['group_name'].value()

        current_members = []
        for member in breed_group.group_members.all():
            current_members.append(member)
        breed_group.group_members.clear()

        if request.user in attached_service.contributors.all():
            if not Approval.objects.filter(breed_group=breed_group).exists():
                BreedGroup.objects.filter(id=breed_group.id).update(state=States.EDITED)

                data = serializers.serialize('yaml', [breed_group, ])

                # create approval object
                Approval.objects.create(account=attached_service,
                                        user=request.user,
                                        type='edit',
                                        breed_group=breed_group,
                                        data=data)

                # reset group members
                breed_group.group_members.clear()
                for pedigree in current_members:
                    breed_group.group_members.add(pedigree)

        else:
            # variable to check that 1 male was given and at least 1 female was given
            male_count = 0
            female_count = 0
            
            # get the input members
            member_index = 0
            member_inputs = []
            while request.POST.get(f'member-{member_index}'):
                member_inputs.append(request.POST.get(f'member-{member_index}'))
                member_index += 1
            # create list of group members to be added after the members are checked
            group_members = []
            for id in member_inputs:
                # increment male_count if it's male, female_count if it's female
                if 'M | ' in id:
                    male_count += 1
                if 'F | ' in id:
                    female_count += 1
                
                id = id[4:]
                pedigree = Pedigree.objects.get(account=attached_service, reg_no=id)
                group_members.append(pedigree)

            # check number of males and females given is correct
            if male_count != 1:
                # reset group members
                breed_group.group_members.clear()
                for pedigree in current_members:
                    breed_group.group_members.add(pedigree)
                return HttpResponse(dumps({'result': 'fail', 'msg': 'Number of males must be one!'}))
            if female_count < 1:
                # reset group members
                breed_group.group_members.clear()
                for pedigree in current_members:
                    breed_group.group_members.add(pedigree)
                return HttpResponse(dumps({'result': 'fail', 'msg': 'Number of females must be at least one!'}))

            # delete any existed approvals
            approvals = Approval.objects.filter(breed_group=breed_group)
            for approval in approvals:
                approval.delete()
            breed_group.state = States.APPROVED

            # add group members to breed group
            for member in group_members:
                breed_group.group_members.add(member)
            
            breed_group.save()

        return HttpResponse(dumps({"result": "success"}))
    else:
        if breed_group.state == States.EDITED:
            approval = Approval.objects.get(breed_group=breed_group)
            for obj in serializers.deserialize("yaml", approval.data):
                obj.object.state = 'edited'
                breed_group = obj.object
        breed_group_form = BreedGroupForm()
        # get any existing members
        for pedigree in breed_group.group_members.all():
            members.append(pedigree.reg_no)

    return render(request, 'edit_breed_group_form.html', {'breed_group_form': breed_group_form,
                                                          'breed_group': breed_group,
                                                          'members': members,
                                                          'breeders': Breeder.objects.filter(account=attached_service),
                                                          'breeds': Breed.objects.filter(account=attached_service)})

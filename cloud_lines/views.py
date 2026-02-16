from django.core.exceptions import PermissionDenied
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, HttpResponse, HttpResponseRedirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.datastructures import MultiValueDictKeyError
from django.contrib.auth.models import User
from django.conf import settings as django_settings
from .models import Service, Page, Gallery, Faq, Testimonial, LargeTierQueue, Blog
from .forms import ContactForm, BlogForm
from account.models import UserDetail, AttachedService
from account.views import get_main_account, send_mail, has_permission, redirect_2_login, get_stripe_secret_key, get_stripe_public_key
from account.graphs import get_graphs
from django.conf import settings
import json
import stripe
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pedigree.models import Pedigree
from breed.models import Breed
from breeder.models import Breeder
from breed_group.models import BreedGroup
from django.db.models import Q
from urllib.parse import urlparse
from re import match
from cloudlines.constants import States, PedigreeStatus, PedigreeSex, ServiceNames
from .tasks import provision_large_tier
import requests


@login_required(login_url="/account/login")
def dashboard(request):
    main_account = get_main_account(request.user)
    if main_account.domain and not match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return HttpResponseRedirect(main_account.domain)

    total_pedigrees = Pedigree.objects.filter(account=main_account).exclude(state=States.UNAPPROVED).count()
    top_pedigrees = Pedigree.objects.filter(account=main_account).order_by('-date_added').exclude(state=States.UNAPPROVED)[:5]
    breed_groups = BreedGroup.objects.filter(account=main_account).order_by('-date_added').exclude(state=States.UNAPPROVED)[:5]
    latest_breeders = Breeder.objects.filter(account=main_account).order_by('-id')[:5]

    if total_pedigrees > 0 \
            and Breed.objects.filter(account=main_account).exists() \
            and len(latest_breeders) > 0:
        
        user_graphs = json.loads(request.user.user.first().graphs)
        
        # total pedigrees added graph
        total_added_chart = {}
        if 'total_added' in user_graphs['selected']:
            current_year = datetime.now().year
            date = datetime.now() - relativedelta(years=9)
            previous_year_count = 0
            for year in [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]:
                year_count = previous_year_count + Pedigree.objects.filter(account=main_account, 
                                    date_added__year=current_year-year).exclude(state=States.UNAPPROVED).count()
                previous_year_count = year_count
                total_added_chart[date.strftime("%Y")] = {'pedigrees_added': year_count}
                if year != 0:
                    date = date.replace(day=1)
                    date = date + relativedelta(years=1)

        # number of pedigrees registered graph
        registered_chart = {}
        if 'registered' in user_graphs['selected']:
            # get the dictionary of breeds mapped to amount of pedigrees for each year
            current_year = datetime.now().year
            date = datetime.now() - relativedelta(years=9)
            previous_year_count = 0
            for year in [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]:
                registered_chart[date.year] = {}
                for breed in Breed.objects.filter(account=main_account):
                    registered_chart[date.year][breed.breed_name] = Pedigree.objects.filter(breed=breed, 
                                                        account=main_account, date_of_registration__year=date.year).exclude(state=States.UNAPPROVED).count()
                
                if year != 0:
                    date = date.replace(day=1)
                    date = date + relativedelta(years=1)

            # make a dictionary of breeds and their colours
            counter = 0
            colours = ['#292b2c', '#44AAAC', '#AC4476', '#0275d8', '#FFC0CB']
            registered_chart['breeds'] = {}
            for breed in Breed.objects.filter(account=main_account):
                registered_chart['breeds'][breed.breed_name] = colours[counter]
                counter += 1
        # number of pedigrees (male/female) currently alive graph
        current_alive_chart = {}
        if 'current_alive' in user_graphs['selected']:
            for breed in Breed.objects.filter(account=main_account):
                current_alive_chart[breed] = {'male': Pedigree.objects.filter(Q(breed__breed_name=breed, account=main_account) & Q(sex=PedigreeSex.MALE) & Q(status=PedigreeStatus.ALIVE)).exclude(state=States.UNAPPROVED).count(),
                                    'female': Pedigree.objects.filter(Q(breed__breed_name=breed, account=main_account) & Q(sex=PedigreeSex.FEMALE) & Q(status=PedigreeStatus.ALIVE)).exclude(state=States.UNAPPROVED).count()}
        # number of pedigrees born graph
        born_chart = {}
        if 'born' in user_graphs['selected']:
            # get the dictionary of breeds mapped to amount of pedigrees for each year
            current_year = datetime.now().year
            date = datetime.now() - relativedelta(years=9)
            previous_year_count = 0
            for year in [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]:
                born_chart[date.year] = {}
                for breed in Breed.objects.filter(account=main_account):
                    born_chart[date.year][breed.breed_name] = Pedigree.objects.filter(breed=breed, 
                                                        account=main_account, dob__year=date.year).exclude(state=States.UNAPPROVED).count()
                
                if year != 0:
                    date = date.replace(day=1)
                    date = date + relativedelta(years=1)
            # make a dictionary of breeds and their colours
            counter = 0
            colours = ['#292b2c', '#44AAAC', '#AC4476', '#0275d8', '#FFC0CB']
            born_chart['breeds'] = {}
            for breed in Breed.objects.filter(account=main_account):
                born_chart['breeds'][breed.breed_name] = colours[counter]
                counter += 1
    else:
        return redirect('welcome')

    # updates
    try:
        get_updates_json = requests.get('https://cloud-lines.com/api/updates/?format=json')
        updates = get_updates_json.json()
        updates = updates['results']
    except (ConnectionError, KeyError):
        updates = {}

    return render(request, 'dashboard.html', {'total_pedigrees': total_pedigrees,
                                              'top_pedigrees': top_pedigrees,
                                              'latest_breeders': latest_breeders,
                                              'breed_groups': breed_groups,
                                              'registered_chart': registered_chart,
                                              'total_added_chart': total_added_chart,
                                              'current_alive_chart': current_alive_chart,
                                              'born_chart': born_chart,
                                              'user_graphs': json.loads(request.user.user.first().graphs),
                                              'site_graphs': json.loads(get_graphs()),
                                              'updates': updates})


@login_required(login_url="/account/login")
def select_graph(request):
    # check permission (this is only used to receive POST requests)
    if request.method == 'GET':
        return redirect_2_login(request)
    elif request.method == 'POST':
        if not has_permission(request, {'read_only': True, 'contrib': True, 'admin': True, 'breed_admin': True}):
            raise PermissionDenied()
    else:
        raise PermissionDenied()

    user = request.user.user.first()

    if request.POST.get('action') == 'remove':
        try:
            # remove the graph
            graphs = json.loads(user.graphs)
            graphs['selected'].remove(request.POST.get('graph'))
            
            # unset whether max graphs is reached if we need to
            if graphs['max_reached'] and len(graphs['selected']) < 2:
                graphs['max_reached'] = False

            # save changes
            user.graphs = json.dumps(graphs)
            user.save()
        except ValueError:
            return HttpResponse(json.dumps({'result': 'fail'}))
    elif request.POST.get('action') == 'change':
        try:
            # remove the graph
            graphs = json.loads(user.graphs)
            graphs['selected'].remove(request.POST.get('change_from'))
            graphs['selected'].append(request.POST.get('graph'))

            # save changes
            user.graphs = json.dumps(graphs)
            user.save()
        except ValueError:
            return HttpResponse(json.dumps({'result': 'fail'}))
    elif request.POST.get('action') == 'add':
        try:
            # remove the graph
            graphs = json.loads(user.graphs)
            graphs['selected'].append(request.POST.get('graph'))

            # set whether max graphs is reached if we need to
            if not graphs['max_reached'] and len(graphs['selected']) >= 2:
                graphs['max_reached'] = True

            # save changes
            user.graphs = json.dumps(graphs)
            user.save()
        except ValueError:
            return HttpResponse(json.dumps({'result': 'fail'}))

    #if not json.loads(user_detail.graphs).max_reached

    return HttpResponse(json.dumps({'result': 'success'}))


def home(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return redirect('dashboard')
    return render(request, 'home.html', {'services': Service.objects.all(),
                                         'testimonials': Testimonial.objects.all(),
                                         'images': Gallery.objects.all()})


def about(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return redirect('dashboard')
    return render(request, 'std_page.html', {'content': Page.objects.get(title='About'),
                                             'services': Service.objects.all()})


def extras(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return redirect('dashboard')
    return render(request, 'std_page.html', {'content': Page.objects.get(title='Extras'),
                                             'services': Service.objects.all()})


def faqs(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return redirect('dashboard')
    return render(request, 'faqs.html', {'faqs': Faq.objects.all(),
                                         'services': Service.objects.all()})


def services(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return redirect('dashboard')
    return render(request, 'services.html', {'services': Service.objects.all()})


def blog(request):
    if request.POST:
        if request.POST['articleID'] == '0':
            # new article
            new_blog = Blog.objects.create(title=request.POST['title'],
                                           content=request.POST['content'])
            try:
                new_blog.video = request.POST['video']
            except MultiValueDictKeyError:
                # no video link
                pass

            try:
                new_blog.image = request.FILES['image']
            except MultiValueDictKeyError:
                # no image
                pass

            new_blog.save()
        else:
            blog = Blog.objects.get(id=request.POST['articleID'])
            blog.title = request.POST['title']
            blog.content = request.POST['content']
            try:
                blog.video = request.POST['video']
            except MultiValueDictKeyError:
                # no video link
                pass

            blog.save()

    blog_form = BlogForm()
    articles = Blog.objects.all()
    return render(request, 'blog.html', {'articles': articles,
                                         'blog_form': blog_form})


def blog_article(request, id, title):
    article = Blog.objects.get(id=id)
    return render(request, 'single_blog.html', {'article': article})


@login_required(login_url="/account/login")
def delete_blog(request, id):
    if request.POST:
        if request.user.is_superuser:
            Blog.objects.get(id=id).delete()

    blog_form = BlogForm()
    articles = Blog.objects.all()
    return render(request, 'blog.html', {'articles': articles,
                                         'blog_form': blog_form})


def contact(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return HttpResponseRedirect('https://cloud-lines.com/contact')
    contact_form = ContactForm(request.POST or None, request.FILES or None)
    if request.POST:
        if contact_form.is_valid():
            contact_form.save()

            name = request.POST.get('name')
            email_address = request.POST.get('email')
            phone = request.POST.get('phone')
            service = request.POST.get('service')
            service = Service.objects.get(id=service)
            subject = request.POST.get('subject')
            message_body = request.POST.get('message')

            # send email to user
            email_body = """
                            <p><strong>Thank you for message!</strong></p>
            
                            <p>We have received your message and will be in contact with you soon.</p>
            
                            <p><strong>Copy of your message</strong></p>
            
                            <p>{}</p>
                            <p>{}</p>""".format(subject, message_body)
            send_mail('Cloudlines message confirmation', name, email_body, send_to=email_address)

            # send mail to cloudlines
            email_body = """
                            <p><strong>New message from {}</strong></p>
                            <p>Email: {}</p>
                            <p>Phone: {}</p>
                            <p>Service: {}</p>
                            <p>{}</p>
                            <p>{}</p>""".format(name, email_address, phone, service.service_name, subject, message_body)
            send_mail('Cloudlines contact request!', 'Cloudlines Team', email_body, reply_to=email_address)

            message = {'message': "Thank you for your email, we'll be in touch soon!"}

            return HttpResponse(json.dumps(message), content_type='application/json')
        else:
            message = {'message': "Oops! Looks like the form wasn't valid."}

            return HttpResponse(json.dumps(message), content_type='application/json')
    else:
        contact_form = ContactForm()
        return render(request, 'contact.html', {'services': Service.objects.all(),
                                                'contact_form': contact_form})


def privacy_policy(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return redirect('dashboard')
    return render(request, 'std_page.html', {'content': Page.objects.get(title='privacy policy'),
                                             'services': Service.objects.all()})


def gdpr(request):
    if match('(.*).cloud-lines.com', request.META['HTTP_HOST']):
        return redirect('dashboard')
    return render(request, 'std_page.html', {'content': Page.objects.get(title='gdpr'),
                                             'services': Service.objects.all()})


def order(request, service=1):
    context = {}
    if 'id' in request.GET:
        # get service the user wants to upgrade to
        context['requested_service'] = Service.objects.get(id=request.GET['id'])
    elif service:
        context['requested_service'] = Service.objects.get(id=service)

    if 'upgrade' in request.GET:
        try:
            context['customer'] = stripe.Customer.retrieve(context['user_detail'].stripe_id)
        except stripe.error.InvalidRequestError:
            pass

        # get the attached_service to upgrade
        if AttachedService.objects.filter(user=context['user_detail'],
                                          id=request.GET['upgrade']).exists():
            context['upgrade'] = True
            context['attached_service_upgrade'] = request.GET['upgrade']

    context['services'] = Service.objects.filter(active=True)
    context['stripe_pk'] = get_stripe_public_key(request)

    return render(request, 'order.html', context)


def order_subscribe(request):
    if request.method == 'POST':
        stripe.api_key = get_stripe_secret_key(request)
        data = json.loads(request.body.decode('utf-8'))
        service = Service.objects.get(price_per_month=data['checkout-form-service'])
        if data['checkout-form-sub-domain']:
            domain = 'https://{}.cloud-lines.com'.format(data['checkout-form-sub-domain'])
        else:
            domain = ''

        # get or create user
        user, created = User.objects.get_or_create(email=data['checkout-form-owner-email'],
                                                   defaults={
                                                       'username': data['checkout-form-owner-email'],
                                                       'first_name': data['checkout-form-owner-first-name'],
                                                       'last_name': data['checkout-form-owner-second-name']})
        # get or create userdetail
        user_detail, created = UserDetail.objects.get_or_create(user=user,
                                                                defaults={'phone': data['checkout-form-owner-phone']})
        # get or create attached service
        # when it's getting an existing service it's an upgrade situation
        attached_service, created = AttachedService.objects.get_or_create(user=user_detail, domain=domain,
                                                                            defaults={
                                                                                'animal_type': data['checkout-form-animal-type'],
                                                                                'site_mode': data['checkout-form-site-mode'],
                                                                                'domain': domain,
                                                                                'install_available': False,
                                                                                'service': service,
                                                                                'increment': data['checkout-form-payment-inc'].lower(),
                                                                                'active': False})
        user_detail.current_service = attached_service
        user_detail.save()

        # stripe bit
        if not user_detail.stripe_id:
            # create stripe user
            if request.user.is_superuser:
                stripe.api_key = settings.STRIPE_TEST_SECRET_KEY
            else:
                stripe.api_key = settings.STRIPE_SECRET_KEY
            customer = stripe.Customer.create(
                name=f"{data['checkout-form-owner-first-name']} {data['checkout-form-owner-second-name']}",
                email=data['checkout-form-owner-email'],
                phone=data['checkout-form-owner-phone'],
                address={'postal_code': data['checkout-form-owner-post-code']}
            )
            customer_id = customer['id']
            # update user datail
            UserDetail.objects.filter(id=user_detail.id).update(stripe_id=customer_id)
        else:
            customer = stripe.Customer.modify(
                user_detail.stripe_id,
                name=f"{data['checkout-form-owner-first-name']} {data['checkout-form-owner-second-name']}",
                email=data['checkout-form-owner-email'],
                phone=data['checkout-form-owner-phone'],
                address={'postal_code': data['checkout-form-owner-post-code']}
            )
        
        # get price ID
        if request.META['HTTP_HOST'] in django_settings.TEST_STRIPE_DOMAINS:
            if data['checkout-form-payment-inc'].lower() == 'yearly':
                price = service.yearly_test_id
            else:
                price = service.monthly_test_id
        else:
            if data['checkout-form-payment-inc'].lower() == 'yearly':
                price = service.yearly_id
            else:
                price = service.monthly_id
        
        # create session
        session = stripe.checkout.Session.create(
            ui_mode='embedded',
            payment_method_types=['card'],
            line_items=[
                {
                    "price": price,
                    "quantity": 1,
                },
            ],
            mode='subscription',
            customer=customer.id,
            return_url=f"{settings.HTTP_PROTOCOL}://{request.META['HTTP_HOST']}/order/success/{attached_service.id}",
        )
        attached_service.stripe_payment_token = session['id']
        attached_service.save()
        return JsonResponse({'success': True, 'clientSecret': session.client_secret})

    return JsonResponse({'success': False})


def order_success(request, attached_service_id):
    stripe.api_key = get_stripe_secret_key(request)
    large_tier = ServiceNames.LARGE_TIERS
    # get the attached service object
    attached_service = AttachedService.objects.get(id=attached_service_id)

    try:
        session = stripe.checkout.Session.retrieve(
            attached_service.stripe_payment_token,
        )
    except stripe.error.StripeError as e:
        # Handle error
        return JsonResponse({'error': str(e)}, status=400)

    if session.payment_status == 'paid':
        # Session was successful
        # update the users attached service to be active
        attached_service.subscription_id = session.get("subscription", None)
        attached_service.active = True
        attached_service.save()

        # send confirmation email
        if attached_service.service.service_name in large_tier:
            body = """
                Congratulations on purchasing a new Cloudlines {} service!
                Your new service is building now. We will send you another email once it's built and ready to access.

                Remember you can always use the in built feature to import any existing data but if you would prefer you can
                <a href="https://cloud-lines.com/contact">Contact us</a> and we'd be happy to help.

            """.format(attached_service.service.service_name, )
        else:
            body = """
                Congratulations on purchasing a new Cloudlines {} service!
                To access your new service click <a href="https://cloud-lines.com/dashboard"> HERE</a>. You should
                find everything you need to get started there but do let is know if you have any questions.
            """.format(attached_service.service.service_name)
        try:
            send_mail('New subscription!', request.user, body, send_to=attached_service.user.user.email)
            send_mail('New subscription!', request.user, body, reply_to=attached_service.user.user.email)
        except Exception as err:
            print(err)

        # start build
        if attached_service.service.service_name in large_tier:
            parsed_uri = urlparse(attached_service.domain)
            domain_parts = parsed_uri.netloc.split('.')
            sub_domain = domain_parts[0] if len(domain_parts) > 2 else None
            queue_item = LargeTierQueue.objects.create(subdomain=sub_domain, user=attached_service.user.user, user_detail=attached_service.user, attached_service=attached_service)

            provision_large_tier.delay(queue_item.id)
            return redirect('build', queue_item.id)
        else:
            return redirect('dashboard')
    else:
        raise Http404("Payment not successful.")  # replace with your actual error handling


def build(request, build_id):
    queue_item = LargeTierQueue.objects.get(id=build_id)
    return render(request, 'build.html', {'queue_item': queue_item})


def send_payment_error(e):
    body = e.json_body
    err = body.get('error', {})

    feedback = "Status is: %s" % e.http_status
    feedback += "<br>Type is: %s" % err.get('type')
    feedback += "<br>Code is: %s" % err.get('code')
    feedback += "<br>Message is: %s" % err.get('message')
    return feedback


def activate_primary_account(request, service):
    user_details = UserDetail.objects.get(user=request.user)
    try:
        primary_account = AttachedService.objects.get(id=service)
    except AttachedService.DoesNotExist:
        return redirect('dashboard')

    if AttachedService.objects.filter(id=service, admin_users=request.user, active=True).exists()\
            or AttachedService.objects.filter(id=service, read_only_users=request.user, active=True).exists() \
            or AttachedService.objects.filter(id=service, user=user_details, active=True).exists():
        UserDetail.objects.filter(user=request.user).update(current_service=primary_account)

    return redirect('dashboard')


def know_more(request):
    if request.POST:
        body = """
            Contact request: {}
            """.format(request.POST.get('contact'))
        send_mail('Contact Request', 'Cloudlines Team', body)
    return HttpResponse(True)


def get_build_status(request):
    if request.method == 'POST':
        queue_id = request.POST.get('build_id')
        queue_item = get_object_or_404(LargeTierQueue, id=queue_id)
        
        status = 'complete' if queue_item.build_state == 'complete' else queue_item.build_status

        response_data = {
            'status': status,
            'percent': queue_item.percentage_complete
        }
        return JsonResponse(response_data)


def robots(request):
    return render(request, 'robots.txt')
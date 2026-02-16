from django import template
from django.template import Variable, VariableDoesNotExist

from datetime import datetime
from cloudlines.constants import BnChildStatus

register = template.Library()


@register.simple_tag
def pedigree_column_data(pedigree, data):
    pedigree_context = {'pedigree': pedigree}
    try:
        value = Variable(f"pedigree.{data['db_id']}").resolve(pedigree_context)
    except VariableDoesNotExist:
        value = ""

    # upper/title
    if data['upper']:
        try:
            value = value.upper()
        except AttributeError:
            # must be a NoneType
            pass
    else:
        try:
            value = value.title()
        except AttributeError:
            # must be a decimal
            pass

    # html
    if data['html'] != "":
        value = data['html'].replace('%REPLACEME%', value)
        return value
    else:
        return value


@register.filter
def price(value):
    if value != "0":
        try:
            return "{:.2f}".format(float(value) / 100)
        except ValueError:
            return 0
    else:
        return 0


@register.filter
def datefield(value):
    return str(value)


@register.filter
def epochtodate(value):
    return str(datetime.fromtimestamp(value).strftime("%m/%d/%Y, %H:%M:%S"))


@register.filter
def percent(value):
    try:
        return f"{float(value) * 100:.2f}%"
    except (ValueError, TypeError):
        return "Error generating percentace"


@register.filter
def get_living_births(value):
    count = 0
    for birth in value.births.all():
        if birth.status == BnChildStatus.ALIVE:
            count += 1
    return count


@register.filter
def get_deceased_births(value):
    count = 0
    for birth in value.births.all():
        if birth.status != BnChildStatus.ALIVE:
            count += 1
    return count

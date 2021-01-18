import csv
import datetime
import io
import itertools
import json
import os
import uuid
from typing import Iterator, Tuple

import xlrd
import xlsxwriter
from decouple import Config, RepositoryEnv, UndefinedValueError
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')
ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')


def excel_column_generator() -> Iterator[Tuple[int, str]]:
    """A generator which outputs the string representation of an Excel column given a number

    Args:
        col_num (int): The column number which will map to a string. Ex: 52 -> "AZ"

    Yields:
        Iterator[Tuple[int, str]]: An iterator which outputs the string representation of the column
    """
    def get_next(col):
        """Helper function which recursively computes the next excel column, given the current column.
        """
        if col == '':
            # Trivial Case
            return ''
        if len(col) == 1:
            # Base case. It's much more easier than it looks!
            return chr(((ord(col) + 1) % ord('A')) % 26 + ord('A'))
        else:
            # Subproblem: Get the remainder and add to the previous
            # substring based on conditions
            remainder = get_next(col[-1])
            if remainder == 'A':
                if col == len(col) * 'Z':
                    # All characters are 'Z'
                    # Make them into 'A' and add the character
                    return (len(col) + 1) * 'A'
                else:
                    return get_next(col[:-1]) + remainder
            else:
                return col[:-1] + remainder

    next_col = "A"
    count = 1
    while True:
        yield (count, next_col)
        count += 1
        next_col = get_next(next_col)


def fetch_bot_data(bot_id, fields, column_names=None, frontend_override=False, send_email=False, email=None, fmt='csv', fetch_leads=False, export_only_lead_fields=True, filters={}):
    chatbot = Chatbox.objects.filter(pk=bot_id)
    owner = chatbot.first().owner
    queryset = ChatRoom.objects.using(owner.ext_db_label).filter(bot_id=bot_id).order_by('-created_on')
    if queryset.count() == 0:
        return HttpResponse(f"Bot {bot_id} not found in clientwidget.ChatRoom", status=404)
    
    name_queryset = chatbot
    if name_queryset.count() == 0:
        return HttpResponse(f"Bot {bot_id} not found in chatbox.Chatbox", status=404)
    
    instance = name_queryset.first()
    bot_name = instance.title
    lead_json = instance.bot_lead_json
    file_name = bot_name

    flag = False

    if fields is None:
        # We need to add all fields
        flag = True
        fields = [field.get_attname_column()[1] for field in ChatRoom._meta.fields if field.get_attname_column()[1] not in ['room_id', 'variables', 'bot_info', 'messages', 'bot_id', 'assignment_type', 'num_msgs']]
        lead_fields = ['visitor_id', 'room_name', 'created_on', 'updated_on', 'end_time', 'channel_id']
        fields = lead_fields
    
    if send_email == True or flag == True:
        # Now add variables if send_email = True
        # We already took care of it during the export API!
        variable_json = instance.bot_variable_json
        variable_names = instance.variable_columns

        if export_only_lead_fields == True:
            if isinstance(lead_json, dict):
                variable_names = list(lead_json.keys())
            else:
                variable_names = []

        if variable_names is None:
            # Fallback option
            if variable_json is None:
                variable_names = []
            else:
                if export_only_lead_fields == True:
                    if isinstance(lead_json, dict):
                        variable_names = list(lead_json.keys())
                    else:
                        variable_names = []
                else:
                    if isinstance(variable_json, dict):
                        variable_names = list(variable_json.keys())
                    else:
                        variable_names = []
        
        if frontend_override == False:
            if export_only_lead_fields == True:
                if isinstance(lead_json, dict):
                    variable_names = list(lead_json.keys())
                else:
                    variable_names = []
            fields = variable_names + fields
        
    # Escape any double quotes in the name (HTTP standard)
    file_name = file_name.replace('"', r'\"')

    if fmt == 'csv':
        if send_email == False:
            # Use content_type rather than mime_type
            response = HttpResponse(content_type=f'text/{fmt}')
            response['Content-Disposition'] = f'attachment;filename="{file_name}_history.{fmt}"'
            writer = csv.writer(response)
        else:
            # Set the writer for a csv file
            csvfile = io.StringIO()
            writer = csv.writer(csvfile)

        # Write the headers first
        headers = []

        for idx, field in enumerate(fields):
            if field is not None:
                if frontend_override:
                    headers.append(column_names[idx])
                else:
                    headers.append(field)
            else:
                pass
        
        writer.writerow(headers)

        # Filter by leads, if fetch_leads is True
        if fetch_leads == True:
            queryset = queryset.filter(is_lead=True)
        
        if 'start_date' in filters:
            start_date = filters['start_date']
        else:
            start_date = None
        
        if 'end_date' in filters:
            end_date = filters['end_date']
        else:
            end_date = None
        
        if start_date is not None and end_date is not None:
            queryset = queryset.filter(created_on__range=[start_date, end_date])

        # Now write the data
        for obj in queryset:
            row = []
            for idx, field in enumerate(fields):
                if field is None:
                    continue
                elif hasattr(obj, field):
                    if field in ['created_on', 'updated_on', 'end_time']:
                        if getattr(obj, field) is not None:
                            attribute = timezone.template_localtime(getattr(obj, field)) + datetime.timedelta(minutes=owner.utc_offset)
                        else:
                            attribute = ""
                    else:
                        attribute = getattr(obj, field)
                    row.append(attribute)
                else:
                    # Probably a variable
                    variables = getattr(obj, 'variables')
                    if field in variables:
                        row.append(variables[field])
                    else:
                        # This variable doesn't exist. Keep it as empty
                        row.append("")
                        # return HttpResponse(f"Error during processing request. Field \"{field}\" does not exist", status=400), False
            writer.writerow(row)
        
        if send_email == True:
            # Attach the files
            email.attach(f'{file_name}.csv', csvfile.getvalue(), 'text/csv')
            return None, True
        else:
            return response, True
    
    elif fmt == 'xlsx':
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, options={'remove_timezone': True})
        worksheet = workbook.add_worksheet()

        columns = len(fields)

        header_generator = excel_column_generator()
        
        # Write the headers first
        headers = []

        row = 1 # type: ignore

        for idx, field in enumerate(fields):
            if field is not None:
                _, column = next(header_generator)
                if frontend_override:
                    worksheet.write(column + str(row), column_names[idx])
                else:
                    worksheet.write(column + str(row), field)
            else:
                pass

        for obj in queryset:
            body_generator = excel_column_generator()
            _, column = next(body_generator)
            row += 1 # type: ignore
            for idx, field in enumerate(fields):
                if field is None:
                    continue
                elif hasattr(obj, field):
                    attribute = getattr(obj, field)
                else:
                    # Probably a variable
                    variables = getattr(obj, 'variables')
                    if field in variables:
                        attribute = variables[field]
                    else:
                        # This variable doesn't exist. Keep it empty
                        attribute = ""
                        # return HttpResponse(f"Error during processing request. Field \"{field}\" does not exist", status=400), False
                
                if field in ['created_on', 'updated_on', 'end_time']:
                    if attribute is not None:
                        attribute = timezone.template_localtime(attribute) + datetime.timedelta(minutes=owner.utc_offset)
                    else:
                        attribute = ""

                # Now process the attribute
                if isinstance(attribute, uuid.UUID):
                    # UUID object can't be JSON Serialized
                    attribute = str(attribute)
                elif isinstance(attribute, datetime.datetime):
                    # datetime object cannot be JSON serializaed
                    attribute = str(attribute)
                elif isinstance(attribute, str):
                    # Don't serialize strings
                    pass
                else:
                    # Others can be JSON serialized
                    attribute = json.dumps(attribute)
                worksheet.write(column + str(row), attribute)
                _, column = next(body_generator)

        workbook.close()

        if send_email == True:
            # Attach the files
            email.attach(f"{file_name}.{fmt}", output.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            return None, True
        else:
            response = HttpResponse(content_type='application/vnd.ms-excel')
            response['Content-Disposition'] = f'attachment;filename="{file_name}_history.{fmt}"'
            response.write(output.getvalue())

            # return the response
            return response, True


def export_chat_data(request, bot_id: uuid.UUID, fields: tuple, fmt: str, send_email=False, fetch_leads=False, export_only_lead_fields=True, filters={}) -> HttpResponse:
    """Exports the chat data by converting it into a particular format

    Args:
        request: The http request
        bot_id (uuid.UUID): The bot ID
        fields (tuple): A tuple of all the necessary fields (column names)
        fmt (str): The format of the output file (.csv, .xlsx, .pdf)
        send_email (bool): Sending an email to the user instead of downloading it directly
        fetch_leads (bool): A filter condition on fetching only the lead data. If this is `False`, it will fetch every chat

    Returns:
        HttpResponse: A Http Response object
    """
    # Check if frontend wants to override our column list
    if f'chatdata_fields_{bot_id}' in request.session and f'chatdata_column_names_{bot_id}' in request.session:
        frontend_override = True
        fields, column_names = request.session[f'chatdata_fields_{bot_id}'], request.session[f'chatdata_column_names_{bot_id}']
        send_multiple = False
    else:
        send_multiple = False
        frontend_override = False
        column_names = None

        # Don't allow this
        return HttpResponse("Columns cannot be blank", status=400)

    if bot_id in ('global', 'user'):
        if f'chatdata_fields_{bot_id}' in request.session:
            del request.session[f'chatdata_fields_{bot_id}']
        if f'chatdata_column_names_{bot_id}' in request.session:
            del request.session[f'chatdata_column_names_{bot_id}']
        frontend_override = False
        send_multiple = True # Sending multiple bots
        column_names = None
    
    if send_email == True:
        # Send an Email
        mail_subject = 'Your Autovista Chatbot History'
        
        if not hasattr(request.user, 'first_name'):
            setattr(request.user, 'first_name', 'User')
        if not hasattr(request.user, 'last_name'):
            setattr(request.user, 'last_name', '')
        
        message = render_to_string('post_chatdata_send.html', {
            'user': request.user,
        })
        to_email = request.user.email
        
        email = EmailMessage(mail_subject, message, to=[to_email])
    else:
        email = None
    
    if fmt == 'csv':
        # Export to .csv
        if isinstance(bot_id, str) and bot_id == 'global':
            # All bots
            queryset = ChatRoom.objects.using(request.user.ext_db_label).all()
        
        elif isinstance(bot_id, str) and bot_id == 'user':
            # Get all the bots for the current user
            queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(admin_id=request.user.id)
        
        if send_multiple == False:
            response, status = fetch_bot_data(bot_id, column_names=column_names, frontend_override=frontend_override, fields=fields[:], send_email=send_email, email=email, fmt='csv', fetch_leads=fetch_leads, export_only_lead_fields=export_only_lead_fields, filters=filters)
            if status == False:
                return response
            if send_email == True:
                email.send()
                return HttpResponse("An Email has been sent to your account. Please check the attachment for details", status=200)
            else:
                return response
        else:
            queryset = queryset.values('bot_id').distinct()
            for instance in queryset:
                bot_id = instance['bot_id']
                response, status = fetch_bot_data(bot_id, column_names=column_names, frontend_override=frontend_override, fields=None, send_email=send_email, email=email, fmt='csv', fetch_leads=fetch_leads, export_only_lead_fields=export_only_lead_fields, filters=filters)
                if status == False:
                    print(f'Warning: Data for Bot {bot_id} possibly corrupted or in an inconsistent format')
            if send_email == True:
                email.send()
                return HttpResponse("An Email has been sent to your account. Please check the attachment for details", status=200)
            else:
                return response

    elif fmt == 'xlsx':
        # Export to xlsx
        if isinstance(bot_id, str) and bot_id == 'global':
            # All bots
            queryset = ChatRoom.objects.using(request.user.ext_db_label).all()

        elif isinstance(bot_id, str) and bot_id == 'user':
            # Get all the bots for the current user
            queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(admin_id=request.user.id)

        if send_multiple == False:
            response, status = fetch_bot_data(bot_id, column_names=column_names, frontend_override=frontend_override, fields=fields[:], send_email=send_email, email=email, fmt='xlsx', fetch_leads=fetch_leads, export_only_lead_fields=export_only_lead_fields, filters=filters)
            if status == False:
                return response
            if send_email == True:
                email.send()
                return HttpResponse("An Email has been sent to your account. Please check the attachment for details", status=200)
            else:
                return response
        else:
            queryset = queryset.values('bot_id').distinct()
            for instance in queryset:
                bot_id = instance['bot_id']
                response, status = fetch_bot_data(bot_id, column_names=column_names, frontend_override=frontend_override, fields=None, send_email=send_email, email=email, fmt='xlsx', fetch_leads=fetch_leads, export_only_lead_fields=export_only_lead_fields, filters=filters)
                if status == False:
                    print(f'Warning: Data for Bot {bot_id} possibly corrupted or in an inconsistent format')

        if send_email == True:
            email.send()
            return HttpResponse("An Email has been sent to your account. Please check the attachment for details", status=200)
        else:
            # return the response
            return response

    else:
        # Bad Request
        return HttpResponse(status=400)

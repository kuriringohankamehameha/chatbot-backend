from celery import task
from django.core.mail import EmailMessage, send_mail
from django.core.mail.message import EmailMultiAlternatives


@task
def acc_email_send(mail_subject, message, to_email):
    email = EmailMessage(mail_subject, message, to=[to_email])
    email.send()

@task
def email_alternative(mail_subject, message, html_text, to_email):
    email = EmailMultiAlternatives(mail_subject, message, to=[to_email])
    email.attach_alternative(html_text, "text/html")
    email.send()
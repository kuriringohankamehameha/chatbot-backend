import os

os.system('python manage.py makemigrations')
os.system('python manage.py migrate')

os.chdir(os.path.join('..', 'frontend/superadmin'))
os.system('yarn install')
os.system('yarn build')

os.chdir(os.path.join('..'))

os.chdir(os.path.join('..', 'frontend/admin'))
os.system('yarn install')
os.system('yarn build')

os.chdir(os.path.join('..'))

os.chdir(os.path.join('..', 'frontend/clientwidget'))
os.system('yarn install')
os.system('yarn chat-build')

os.system('sudo service nginx restart')
os.system('sudo supervisorctl restart autovista_chatbot_gunicorn')
os.system('sudo supervisorctl restart autovista_chatbot_daphne')

# sudo service nginx restart
# sudo supervisorctl restart autovista_chatbot_gunicorn
# sudo supervisorctl restart autovista_chatbot_daphne

# CREATE DATABASE av_chatbot;
# CREATE USER chatbotuser WITH PASSWORD 'Autovista1243';
# ALTER ROLE chatbotuser SET client_encoding TO 'utf8';
# ALTER ROLE chatbotuser SET default_transaction_isolation TO 'read committed';
# ALTER ROLE chatbotuser SET timezone TO 'UTC';
# GRANT ALL PRIVILEGES ON DATABASE av_chatbot TO chatbotuser;
# \q
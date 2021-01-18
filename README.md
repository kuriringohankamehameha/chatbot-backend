# Chatbot-Backend

* Contains the backend code for a production level Chatbot builder application, written primarily using **Django Rest Framework** for the REST API and **Django Channels** to handle Websocket connections on the server-side.
* Has optional support for **Celery**, but is not required.
* **Redis** is a necessary dependency for the backend Cache as well as for Session management.
* Uses **APScheduler** to manage Cronjobs.
* Uses best open source practices and tries to maintain consistency and readability.

-----------------------------------------------------------------

## Instructions

1. Create a fresh virtualenv via:

```bash
pip install virtualenv
virtualenv env
```

2. Activate the virtualenv using: 

Windows:
```bash
. .\env\Scripts\activate
```

OR (Linux)

```bash
source ./env/Scripts/activate
```

3. Install all dependencies

```bash
pip install -r requirements.txt
```

4. Now setup your local settings files (`chatbot/local_settings.py` and `chatbot/.env`). Copy the initial template config files to get started:

```bash
cp ./chatbot/local_settings.example ./chatbot/local_settings.py
cp ./chatbot/env.example ./chatbot/.env
```

Make your necessary config changes in `.env` and continue

5. Setup Django (Migrations, etc):

```bash
python manage.py makemigrations
python manage.py migrate
```

6. Create a Super User to manage the application:

```bash
python manage.py createsuperuser
```

Run the development server using:

```bash
python manage.py runserver 0.0.0.0:8000
```

## Run Celery (Optional):

If the base application is working, you can spawn the celery server using:

```bash
celery worker -A apps.chatbox.tasks --pool=eventlet --loglevel=info
```

## Credits

* Work was done by Vijay Krishna (me)

---------------------------------------------------------
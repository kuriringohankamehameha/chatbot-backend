import os
from apps.chatbox.template import jsString


server_url = 'gaadibazaar.in'
directory_path = os.path.join('staticfiles', 'chatbox', 'bot_js')

for filename in os.listdir(directory_path):
    if filename.endswith('.js'):
        print(f'updating {filename}')
        file_path = os.path.join(directory_path, filename)
        bot_hash = filename.split('.')[0]
        file_obj = open(file_path, 'w')
        file_text = jsString.format(str(server_url), str(bot_hash))
        file_obj.write(file_text)
        file_obj.close()
    
print('updating bot files completed')
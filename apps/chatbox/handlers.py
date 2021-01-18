from apps.clientwidget.models import ClientMediaHandler


def client_media(bot_id, room_id, bot_type, media, media_type, db_label='default'):
    client_media = ClientMediaHandler(room_id=room_id, bot_id=bot_id,
    bot_type=bot_type, media_type=media_type)
    client_media.save(using=db_label)
    client_media.media_file.save(media.name, media, save=True, using=db_label)
    return client_media.media_file.url

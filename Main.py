import os
import sqlite3
import telebot
from datetime import datetime
from telebot import types
import pytesseract
from PIL import Image, ImageDraw, ImageFont

API_TOKEN = '7935568321:AAEGucFIoCoSHllEYx1n6OnzO_9ICjRdj4Y'
ADMIN_IDS = [5801912979]
DB_PATH = 'notes.db'
PHOTO_FOLDER = 'teachdata'

os.makedirs(PHOTO_FOLDER, exist_ok=True)

bot = telebot.TeleBot(API_TOKEN)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS notes (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      date TEXT,
                      subject TEXT,
                      photos TEXT
                      )''')
    conn.commit()
    return conn

def is_admin(user_id):
    return user_id in ADMIN_IDS

admin_state = {}

def extract_text_from_image(image_path):
    """Использует pytesseract для извлечения текста из изображения."""
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang='rus')  # Используйте 'rus' для русского текста
    return text

def generate_image_with_text(text, output_image_path):
    """Создает изображение с распознанным текстом."""
    img_width, img_height = 800, 400
    background_color = (255, 255, 255)
    text_color = (0, 0, 0)
    font_size = 24    

    # Создаем изображение
    img = Image.new('RGB', (img_width, img_height), color=background_color)
    draw = ImageDraw.Draw(img)

    # Загружаем шрифт
    font = ImageFont.truetype("arial.ttf", font_size)

    draw.text((10, 10), text, font=font, fill=text_color)

    img.save(output_image_path)

@bot.message_handler(commands=['start'])
def start_command(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "<b>Привет!</b>\n\nДля того, чтобы добавить новый конспект, напиши название предмета!", parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "<b>Привет!</b>\n\nЧтобы посмотреть конспекты на конкретную дату, напиши /view!\n\n<i>Конспекты иногда могут не загружаться или отсутствовать. Просим заранее прощения</i>", parse_mode="HTML")

@bot.message_handler(func=lambda message: is_admin(message.from_user.id) and message.from_user.id not in admin_state and message.text)
def handle_subject_input(message):
    subject = message.text.strip()
    date = datetime.now().strftime('%d.%m.%Y')

    conn = init_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notes WHERE date = ? AND subject = ?", (date, subject))
    result = cursor.fetchone()
    conn.close()

    if result[0] > 0:
        bot.send_message(message.chat.id, f"<b>Ошибка!</b>\n\nКонспект для предмета {subject} на сегодняшнюю дату ({date}) уже существует.", parse_mode="HTML")
        return

    bot.send_message(message.chat.id, f"<b>Вы ввели предмет: {subject}</b>\n\nСколько фотографий вы хотите загрузить? Введите числом", parse_mode="HTML")
    admin_state[message.from_user.id] = {
        'subject': subject,
        'photos': [],
        'photo_count': 0,
        'photos_received': 0,
        'awaiting_handwriting_check': False  # Новый флаг для отслеживания вопроса о почерке
    }

@bot.message_handler(func=lambda message: message.from_user.id in admin_state and admin_state[message.from_user.id]['photo_count'] == 0 and message.text.isdigit())
def handle_photo_count_input(message):
    count = int(message.text)
    if count > 0:
        admin_state[message.from_user.id]['photo_count'] = count
        bot.send_message(message.chat.id, f"<b>Вы выбрали {count} фотографий.</b>\n\nТеперь отправьте фотографии одну за другой.", parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "<b>Ошибка!</b>\n\nВведите положительное число.", parse_mode="HTML")

@bot.message_handler(content_types=['photo'])
def handle_photo_upload(message):
    if message.from_user.id in admin_state and admin_state[message.from_user.id]['photo_count'] > 0:
        subject_data = admin_state[message.from_user.id]
        subject = subject_data['subject']

        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        photo_path = os.path.join(PHOTO_FOLDER, f"{subject}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
        with open(photo_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        subject_data['photos'].append(photo_path)
        subject_data['photos_received'] += 1

        # Задаем вопрос о разборчивости почерка
        bot.send_message(message.chat.id, "У вас разборчивый почерк? Ответьте 'Да' или 'Нет'.")
        subject_data['awaiting_handwriting_check'] = True
        subject_data['last_photo_path'] = photo_path # Сохраняем путь к фото

@bot.message_handler(func=lambda message: message.from_user.id in admin_state and admin_state[message.from_user.id].get('awaiting_handwriting_check'))
def handle_handwriting_check(message):
    answer = message.text.lower()
    subject_data = admin_state[message.from_user.id]

    if answer == "да":
        # Продолжаем без изменений
        bot.send_message(message.chat.id, "Отлично, продолжаем добавлять фотографии.")
    elif answer == "нет":
        # Используем OCR для извлечения текста и создания изображения с печатным текстом
        photo_path = subject_data['last_photo_path']
        recognized_text = extract_text_from_image(photo_path)

        if recognized_text.strip():
            # Генерируем новое изображение с распознанным текстом
            new_photo_path = os.path.join(PHOTO_FOLDER, f"text_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
            generate_image_with_text(recognized_text, new_photo_path)

            # Заменяем исходное фото на новое
            subject_data['photos'][-1] = new_photo_path
            bot.send_message(message.chat.id, "Текст распознан и добавлен в виде печатного текста.")
        else:
            bot.send_message(message.chat.id, "Не удалось распознать текст. Используем исходное фото.")
    else:
        bot.send_message(message.chat.id, "Пожалуйста, ответьте 'Да' или 'Нет'.")

    subject_data['awaiting_handwriting_check'] = False  # Сбрасываем флаг

    # Проверяем, все ли фотографии загружены
    if subject_data['photos_received'] == subject_data['photo_count']:
        finish_adding_notes(message)

def finish_adding_notes(message):
    subject_data = admin_state.pop(message.from_user.id)
    subject = subject_data['subject']
    photos = ','.join(subject_data['photos'])
    date = datetime.now().strftime('%d.%m.%Y')

    conn = init_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO notes (date, subject, photos) VALUES (?, ?, ?)", (date, subject, photos))
    conn.commit()
    conn.close()

    bot.send_message(message.chat.id, f"<b>Успех!</b>\n\nКонспект для предмета {subject} на {date} успешно добавлен.", parse_mode="HTML")

@bot.message_handler(commands=['view'])
def view_notes(message):
    bot.send_message(message.chat.id, "<b>Просмотр конспектов</b>\n\nВведите дату в формате ДД.ММ.ГГГГ, чтобы увидеть доступные конспекты", parse_mode="HTML")

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text)
def handle_date_input(message):
    input_date = message.text.strip()
    try:
        datetime.strptime(input_date, '%d.%m.%Y') 

        conn = init_db()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT subject FROM notes WHERE date = ?", (input_date,))
        subjects = cursor.fetchall()
        conn.close()

        if subjects:
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            for subject in subjects:
                keyboard.add(types.InlineKeyboardButton(subject[0], callback_data=f"subject_{input_date}_{subject[0]}"))
            bot.send_message(message.chat.id, f"<b>Конспекты за {input_date}</b>\n\nВыберите предмет, нажав на кнопку", reply_markup=keyboard, parse_mode="HTML")
        else:
            bot.send_message(message.chat.id, f"Конспекты за {input_date} не найдены.", parse_mode="HTML")
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат даты. Введите дату в формате ДД.ММ.ГГГГ.", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("subject_"))
def handle_subject_selection(call):
    _, input_date, subject = call.data.split('_')

    conn = init_db()
    cursor = conn.cursor()
    cursor.execute("SELECT photos FROM notes WHERE date = ? AND subject = ?", (input_date, subject))
    photos = cursor.fetchone()
    conn.close()

    if photos:
        photo_paths = photos[0].split(',')
        for photo_path in photo_paths:
            with open(photo_path, 'rb') as photo_file:
                bot.send_photo(call.message.chat.id, photo_file)
    else:
        bot.send_message(call.message.chat.id, f"Конспекты для предмета {subject} за {input_date} не найдены.", parse_mode="HTML")

    bot.answer_callback_query(call.id)

if __name__ == '__main__':
    bot.polling(none_stop=True)
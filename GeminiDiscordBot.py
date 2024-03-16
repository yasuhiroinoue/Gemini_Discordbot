import os
import re

import aiohttp
import discord
import google.generativeai as genai
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image
import io
import base64

message_history = {}

load_dotenv()

GOOGLE_AI_KEY = os.getenv("GOOGLE_AI_KEY")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN4")
MAX_HISTORY = int(os.getenv("MAX_HISTORY"))

#---------------------------------------------AI Configuration-------------------------------------------------

# Configure the generative AI model
genai.configure(api_key=GOOGLE_AI_KEY)
text_generation_config = {
    "temperature": 0.9,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 8192,
}
image_generation_config = {
    "temperature": 0.4,
    "top_p": 1,
    "top_k": 32,
    "max_output_tokens": 2048,
}
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
]
text_model = genai.GenerativeModel(model_name="gemini-pro", generation_config=text_generation_config, safety_settings=safety_settings)
image_model = genai.GenerativeModel(model_name="gemini-pro-vision", generation_config=image_generation_config, safety_settings=safety_settings)


#---------------------------------------------Discord Code-------------------------------------------------
# Initialize Discord bot
bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    print("----------------------------------------")
    print(f'Gemini Bot Logged in as {bot.user}')
    print("----------------------------------------")

#On Message Function
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.mention_everyone:
        await message.channel.send(f'{bot.user}です')
        return

    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        cleaned_text = clean_discord_message(message.content)
        async with message.channel.typing():
            if message.attachments:
                await process_attachments(message, cleaned_text)
            else:
                await process_text_message(message, cleaned_text)

async def process_attachments(message, cleaned_text):
    print(f"New Image Message FROM: {message.author.id}: {cleaned_text}")
    for attachment in message.attachments:
        file_extension = os.path.splitext(attachment.filename.lower())[1]
        ext_to_mime = {'.png': "image/png", '.jpg': "image/jpeg", '.jpeg': "image/jpeg", '.gif': "image/gif", '.webp': "image/webp"}
        if file_extension in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            await message.add_reaction('🎨')
            mime_type = ext_to_mime[file_extension]
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    if resp.status != 200:
                        await message.channel.send('Unable to download the image.')
                        return
                    if MAX_HISTORY == 0:
                        image_data = await resp.read()
                        resized_image_stream = resize_image_if_needed(image_data, file_extension)
                        resized_image_data = resized_image_stream.getvalue()
                        encoded_image_data = base64.b64encode(resized_image_data).decode("utf-8")
                        response_text = await generate_response_with_image_and_text(encoded_image_data, cleaned_text, mime_type)
                        await split_and_send_messages(message, response_text, 1700)
                        return
                    update_message_history(message.author.id, cleaned_text, "user")
                    image_data = await resp.read()
                    resized_image_stream = resize_image_if_needed(image_data, file_extension)
                    resized_image_data = resized_image_stream.getvalue()
                    encoded_image_data = base64.b64encode(resized_image_data).decode("utf-8")
                    response_text = await generate_response_with_image_and_text(encoded_image_data, cleaned_text, mime_type)
                    update_message_history(message.author.id, response_text, "system")
                    await split_and_send_messages(message, response_text, 1700)
        else:
            supported_extensions = ', '.join(ext_to_mime.keys())
            await message.channel.send(f"🗑️ Unsupported file extension. Supported extensions are: {supported_extensions}")

async def process_text_message(message, cleaned_text):
    print(f"New Message FROM: {message.author.id}: {cleaned_text}")
    if "RESET" in cleaned_text.upper():
        message_history.pop(message.author.id, None)
        await message.channel.send(f"🧹 History Reset for user: {message.author.name}")
        return
    await message.add_reaction('💬')
    if MAX_HISTORY == 0:
        response_text = await generate_response_with_text(cleaned_text)
        await split_and_send_messages(message, response_text, 1700)
        return
    update_message_history(message.author.id, cleaned_text, "user")
    formatted_history = get_formatted_message_history(message.author.id)
    response_text = await generate_response_with_text(formatted_history)
    update_message_history(message.author.id, response_text, "system")
    await split_and_send_messages(message, response_text, 1700)

#---------------------------------------------AI Generation History-------------------------------------------------

async def generate_response_with_text(message_text):
    prompt_parts = [message_text]
    print("Got textPrompt: " + message_text)
    response = text_model.generate_content(prompt_parts)
    if(response._error):
        return "❌" +  str(response._error)
    return response.text

async def generate_response_with_image_and_text(image_data, text, mime_type):
    image_parts = [{"mime_type": mime_type, "data": image_data}]
    prompt_parts = [image_parts[0], f"\n{text if text else 'What is this a picture of?'}"]
    response = image_model.generate_content(prompt_parts)
    if(response._error):
        return "❌" +  str(response._error)
    return response.text

#---------------------------------------------Message History-------------------------------------------------

def update_message_history(user_id, text, message_type):
    prefixed_message = f"{message_type}: {text}"
    if user_id in message_history:
        message_history[user_id].append(prefixed_message)
        if len(message_history[user_id]) > MAX_HISTORY:
            message_history[user_id].pop(0)
    else:
        message_history[user_id] = [prefixed_message]

def get_formatted_message_history(user_id):
    return '\n\n'.join(message_history.get(user_id, ["No messages found for this user."]))

def clean_discord_message(input_string):
    bracket_pattern = re.compile(r'<[^>]+>')
    return bracket_pattern.sub('', input_string)

def resize_image_if_needed(image_bytes, file_extension, max_size_mb=5, step=10):
    format_map = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.gif': 'GIF', '.webp': 'WEBP'}
    img_format = format_map.get(file_extension.lower(), 'JPEG')
    img_stream = io.BytesIO(image_bytes)
    img = Image.open(img_stream)
    while img_stream.getbuffer().nbytes > max_size_mb * 1024 * 1024:
        width, height = img.size
        img = img.resize((int(width * (100 - step) / 100), int(height * (100 - step) / 100)), Image.ANTIALIAS)
        img_stream = io.BytesIO()
        img.save(img_stream, format=img_format)
    return img_stream

async def split_and_send_messages(message_system, text, max_length):
    for i in range(0, len(text), max_length):
        await message_system.channel.send(text[i:i+max_length])

# Run the bot
bot.run(DISCORD_BOT_TOKEN)


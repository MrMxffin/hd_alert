import os
import json
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, \
    Chat, ChatMember, ChatMemberUpdated
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, \
    CallbackQueryHandler, ChatMemberHandler
import requests
from datetime import datetime, timedelta
from typing import Optional

# Load environment variables from .env file
load_dotenv()

# Global dictionary to store vote counts for each location message
data_path = os.getenv('PATH_TO_TRACKED_MESSAGES')
tracked_messages = {"messages": []}


def initialize_file(path, default_data):
    """Ensure the file exists and contains the default data if not."""
    if not os.path.exists(path):
        with open(path, 'w+') as file:
            json.dump(default_data, file, indent=2)


def load_tracked_messages():
    global tracked_messages
    initialize_file(data_path, {"messages": []})  # Ensure the file exists
    try:
        with open(data_path, 'r') as file:
            tracked_messages = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading tracked messages: {e}")
        tracked_messages = {"messages": []}  # Reset to default if there's an error


def save_tracked_messages():
    with open(data_path, 'w+') as file:
        json.dump(tracked_messages, file, indent=2)


def clean_old_messages():
    current_time = datetime.now()
    messages_to_keep = [msg for msg in tracked_messages["messages"] if
                        datetime.fromisoformat(msg["delete_time"]) > current_time]
    tracked_messages["messages"] = messages_to_keep
    save_tracked_messages()


# Load tracked messages at the start
load_tracked_messages()

# Get the token from environment variables
TOKEN = os.getenv('TELEGRAM_TOKEN')
OWNER_ID = os.getenv('OWNER_ID')


# Define the function to handle the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [[
        {"text": "Sende derzeitigen Standort.", "request_location": True},
    ]]
    # Ask the user for their location
    await update.effective_message.reply_text(
        "Bitte sende den Ort der Hausdurchsuchung.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Check if the message is from a private chat, group, or channel
    query = ""
    if update.effective_message and update.effective_message.message_thread_id:
        message_thread_id = update.effective_message.message_thread_id
    else:
        message_thread_id = None
    user = update.effective_user
    chat = update.effective_chat
    if chat.type == "supergroup":
        query = f"The User @{user.username} (ID: {user.id}) is requesting to subscribe the supergroup {chat.title} (ID: {chat.id}). Do you approve?"
    elif chat.type == "group":
        query = f"The User @{user.username} (ID: {user.id}) is requesting to subscribe the group {chat.title} (ID: {chat.id}). Do you approve?"
    elif chat.type == "channel":
        query = f"The Channel {chat.title} (ID: {chat.id}) is requesting to subscribe). Do you approve?"
    elif chat.type == "private":
        query = f"User @{user.username} (ID: {user.id}) is requesting to subscribe to the Bot in a private chat. Do you approve?"

    if is_chat_subscribed(chat.id, message_thread_id) and not chat.type == "channel":
        await update.effective_message.reply_text("You are already subscribed.")
    else:
        await context.bot.send_message(
            OWNER_ID,
            query,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes", callback_data=f"approve_{chat.id}_{message_thread_id}"),
                 InlineKeyboardButton("No", callback_data=f"reject_{chat.id}_{message_thread_id}")]
            ])
        )
        if not chat.type == "channel":
            await update.effective_message.reply_text("Your subscription request has been sent to the bot owner.")


# Define the function to handle the location message
def get_channels(path):
    try:
        initialize_file(path, {"channels": []})  # Ensure the file exists
        with open(path, 'r') as file:
            channels_data = json.load(file)
            return channels_data.get('channels', [])
    except FileNotFoundError:
        print(f"Error: File not found at path: {path}")
        return []
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in file: {path}")
        return []


def is_chat_subscribed(chat_id, message_thread_id):
    channels = get_channels(os.getenv("PATH_TO_CHANNELS"))
    filtered_data = [entry for entry in channels if entry["chat_id"] == chat_id]
    if message_thread_id is not None:
        filtered_data = [entry for entry in filtered_data if
                         "message_thread_id" in entry and entry["message_thread_id"] == message_thread_id]
    return len(filtered_data) > 0


def get_location_name(location):
    headers = {
        'Referer': 'https://t.me/mxmxffin',
        'User-Agent': 'Hausdurchsuchungsalarm/1.0 (+https://t.me/hausdurchsuchungsalarm_bot)'
    }

    # Nominatim API endpoint URL
    url = f"https://nominatim.openstreetmap.org/reverse?lat={location.latitude}&lon={location.longitude}&format=json"

    # Make a GET request to the API
    response = requests.get(url, headers=headers)

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Parse the JSON response
        data = response.json()

        # Extract and return the address string
        if 'address' in data:
            address = data['address']
            # Construct the German address format
            address_string = f"{address.get('road')} {address.get('house_number')},\n{address.get('postcode')} {address.get('city')}"
            return address_string
        else:
            return ""
    else:
        # Print an error message if the request was not successful
        print(f"Error: Failed to fetch location details. Status code: {response.status_code}")
        return None


# Define a function to handle the location message
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message.location:
        print("Error: Received a message without location data.")
        return
    else:
        location = update.effective_message.location
        username = update.effective_user.username
        # Initialize vote counts for the new message
        address = get_location_name(location)
        delete_time = (datetime.now() + timedelta(weeks=1)).isoformat()

        # Create a new entry in tracked_messages
        new_message_entry = {
            "address": address,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "username": username,
            "user_votes": {"valid": [], "invalid": []},
            "delete_time": delete_time,
            "messages": []
        }

        # Use your existing logic to send the location to the channels
        channels = get_channels(os.getenv("PATH_TO_CHANNELS"))
        for channel in channels:
            chat_id = channel.get('chat_id')
            message_thread_id = channel.get('message_thread_id')

            # Send the location message with inline keyboard for voting
            sent_message = await context.bot.send_message(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                text=f"Der Nutzer @{username} meldet eine Hausdurchsuchung an folgender Adresse:\n"
                     f"{address}\n",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Valid",
                                          callback_data=f"valid_{location.latitude}_{location.longitude}"),
                     InlineKeyboardButton("Invalid",
                                          callback_data=f"invalid_{location.latitude}_{location.longitude}")]
                ])
            )

            # Send the location coordinates
            await context.bot.send_location(
                chat_id=chat_id,
                location=location,
                message_thread_id=message_thread_id
            )

            # Add the sent message details to the new message entry
            new_message_entry["messages"].append({
                "chat_id": chat_id,
                "message_id": sent_message.message_id
            })

        # Append the new message entry to tracked_messages
        tracked_messages["messages"].append(new_message_entry)

        # Save the updated tracked messages
        save_tracked_messages()

        # Remove the keyboard
        await update.effective_message.reply_text("Vielen Dank für deine Hilfe.", reply_markup=ReplyKeyboardRemove())


# Handle new chat members (when bot is added to a group or channel)
async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle when the bot is added to a channel/group."""
    # Check if the bot is added to a chat and is given admin rights
    new_members = update.message.new_chat_members
    bot_user = context.bot.get_me()  # Get bot info
    chat = update.effective_chat

    # If the bot is added to the group/channel and has admin rights, subscribe it
    for member in new_members:
        if member.id == bot_user.id:
            if chat.type in ["channel"]:
                # Automatically subscribe the chat if bot is added with admin rights
                if context.bot.get_chat_member(chat.id, bot_user.id).status == "administrator":
                    await subscribe(update, context)



def add_chat_to_subscribers(chat_id, message_thread_id=None):
    """Add a chat (group, supergroup, or channel) to the subscribers list."""
    channels_path = os.getenv("PATH_TO_CHANNELS")
    initialize_file(channels_path, {"channels": []})  # Ensure file exists

    try:
        with open(channels_path, 'r') as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Error loading channels from {channels_path}, resetting.")
        data = {"channels": []}

    # Check if chat is already in the list
    for entry in data["channels"]:
        if entry["chat_id"] == chat_id:
            if message_thread_id and "message_thread_id" not in entry:
                # If a thread ID is provided but missing, update the entry
                entry["message_thread_id"] = message_thread_id
                break
            return  # Already subscribed, no need to add again

    # Add new chat entry
    new_entry = {"chat_id": chat_id}
    if message_thread_id:
        new_entry["message_thread_id"] = message_thread_id
    data["channels"].append(new_entry)

    # Save updated list
    with open(channels_path, 'w') as file:
        json.dump(data, file, indent=2)
    print(f"Added new chat: {chat_id}, Thread: {message_thread_id}")


# Define callback function to handle button clicks
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    id_parts = query.data.split('_')
    action = id_parts[0]

    if action == "approve" or action == "reject":
        chat_id = int(id_parts[1])
        message_thread_id = int(id_parts[2]) if len(id_parts) > 2 and id_parts[2].isdigit() else None
        if action == "approve":
            add_chat_to_subscribers(chat_id, message_thread_id)
            await query.edit_message_text("Subscription approved ✅")
        else:
            await query.edit_message_text("Subscription rejected ❌")
        return  # Prevent further processing


async def track_channels (update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat.type != Chat.CHANNEL:
        return
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_admin, is_admin = result

    if not was_admin and is_admin:
        await subscribe(update, context)
    elif was_admin and not is_admin:
        print("unsubscribe")


def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[tuple[bool, bool]]:
    status_change = chat_member_update.difference().get("status")

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_admin = old_status in [
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ]
    is_admin = new_status in [
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ]
    return was_admin, is_admin

# Register handlers
def run_bot():
    try:
        # Initialize the application
        app = ApplicationBuilder().token(TOKEN).build()

        # Register the handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("subscribe", subscribe))
        app.add_handler(ChatMemberHandler(track_channels, ChatMemberHandler.MY_CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.LOCATION, handle_location))
        app.add_handler(CallbackQueryHandler(button_click))

        # Start the bot
        app.run_polling()
    except Exception as e:
        print(f"Error: {e}")

import os
import json
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import requests
from datetime import datetime, timedelta

# Load environment variables from .env file
load_dotenv()

# Global dictionary to store vote counts for each location message
data_path = os.getenv('PATH_TO_TRACKED_MESSAGES')
tracked_messages = {"messages": []}


def initialize_file(path, default_data):
    """Ensure the file exists and contains the default data if not."""
    if not os.path.exists(path):
        with open(path, 'w') as file:
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
    with open(data_path, 'w') as file:
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
    if update.effective_message.message_thread_id:
        message_thread_id = update.effective_message.message_thread_id
    else:
        message_thread_id = None
    user = update.effective_user
    chat = update.effective_chat
    if update.effective_chat.type == "supergroup":
        query = f"The User @{user.username} (ID: {user.id}) is requesting to subscribe the supergroup {chat.title} (ID: {chat.id}). Do you approve?"
    elif update.effective_chat.type == "group":
        query = f"The User @{user.username} (ID: {user.id}) is requesting to subscribe the group {chat.title} (ID: {chat.id}). Do you approve?"
    elif update.effective_chat.type == "channel":
        query = f"The Channel {chat.title} (ID: {chat.id}) is requesting to subscribe). Do you approve?"
    elif update.effective_chat.type == "private":
        query = f"User @{user.username} (ID: {user.id}) is requesting to subscribe to the Bot in a private chat. Do you approve?"

    if is_chat_subscribed(chat.id, message_thread_id):
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
    # Check if a location was shared
    if update.effective_message.location:
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


# Callback function to handle button clicks
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    id_parts = query.data.split('_')
    action = id_parts[0]
    latitude = float(id_parts[1])
    longitude = float(id_parts[2])
    user_id = update.effective_user.id

    # Find the message entry
    message_entry = next((msg for msg in tracked_messages["messages"]
                          if msg["latitude"] == latitude and msg["longitude"] == longitude), None)

    if message_entry:
        if action == "valid":
            if user_id not in message_entry["user_votes"]["valid"]:
                message_entry["user_votes"]["valid"].append(user_id)
                # Remove from invalid votes if present
                if user_id in message_entry["user_votes"]["invalid"]:
                    message_entry["user_votes"]["invalid"].remove(user_id)
        elif action == "invalid":
            if user_id not in message_entry["user_votes"]["invalid"]:
                message_entry["user_votes"]["invalid"].append(user_id)
                # Remove from valid votes if present
                if user_id in message_entry["user_votes"]["valid"]:
                    message_entry["user_votes"]["valid"].remove(user_id)

        # Update all related messages with the new vote counts
        vote_counts = (len(message_entry["user_votes"]["valid"]),
                       len(message_entry["user_votes"]["invalid"]))

        # Get the original message text shared by the user
        address = message_entry["address"]
        username = message_entry["username"]
        original_text = f"Der Nutzer @{username} meldet eine Hausdurchsuchung an folgender Adresse:\n{address}"

        # Update every related message
        for msg in message_entry["messages"]:

            # Calculate the validity percentage
            total_votes = vote_counts[0] + vote_counts[1]
            percent_valid = round(100 * vote_counts[0] / total_votes, 2) if total_votes > 0 else 0

            await context.bot.edit_message_text(
                chat_id=msg["chat_id"],
                message_id=msg["message_id"],
                text=f"{original_text}\n\nValidity: {percent_valid}%",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"Valid ({vote_counts[0]})",
                                          callback_data=f"valid_{latitude}_{longitude}"),
                     InlineKeyboardButton(f"Invalid ({vote_counts[1]})",
                                          callback_data=f"invalid_{latitude}_{longitude}")]
                ])
            )

        # Save the updated tracked messages
        save_tracked_messages()

    # Acknowledge the callback
    await query.answer()


def run_bot():
    try:
        # Initialize the application
        app = ApplicationBuilder().token(TOKEN).build()

        # Register the handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("subscribe", subscribe))
        app.add_handler(MessageHandler(filters.LOCATION, handle_location))
        app.add_handler(CallbackQueryHandler(button_click))

        # Start the bot
        app.run_polling()
    except Exception as e:
        print(f"Error: {e}")

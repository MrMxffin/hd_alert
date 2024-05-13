import os
import json
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import requests

# Global dictionary to store vote counts for each location message
tracked_messages = {}

# Load environment variables from .env file
load_dotenv()

# Get the token from environment variables
TOKEN = os.getenv('TELEGRAM_TOKEN')


# Define a function to handle the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [[
        {"text": "Sende derzeitigen Standort.", "request_location": True},
    ]]
    # Ask the user for their location
    await update.message.reply_text(
        "Bitte sende den Ort der Hausdurchsuchung.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )


# Define a function to handle the location message
def get_channels(path):
    try:
        with open(path, 'r') as file:
            channels_data = json.load(file)
            return channels_data.get('channels', [])
    except FileNotFoundError:
        print(f"Error: File not found at path: {path}")
        return []
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in file: {path}")
        return []


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
    if update.message.location:
        location = update.message.location
        username = update.effective_user.username
        # Initialize vote counts for the new message
        address = get_location_name(location)
        tracked_messages[f"{update.effective_user.id}_{update.message.message_id}"] = {"valid": 0, "invalid": 0, "address":address, "username":username, "user_votes":[]}
        # Use your existing logic to send the location to the channels
        channels = get_channels(os.getenv("PATH_TO_CHANNELS"))
        for channel in channels:
            chat_id = channel.get('chat_id')
            message_thread_id = channel.get('message_thread_id')

            # Send the location message with inline keyboard for voting
            message = await context.bot.send_message(
                chat_id,
                f"Der Nutzer @{username} meldet eine Hausdurchsuchung an folgender Adresse:\n"
                f"{address}\n",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Valid", callback_data=f"valid_{update.effective_user.id}_{update.message.message_id}"),
                     InlineKeyboardButton("Invalid", callback_data=f"invalid_{update.effective_user.id}_{update.message.message_id}")]
                ])
            )

            # Send the location coordinates
            await context.bot.send_location(
                chat_id,
                message_thread_id,
                location=location,
            )

        # Remove the keyboard
        await update.message.reply_text("Vielen Dank für deine Hilfe.", reply_markup=ReplyKeyboardRemove())


# Callback function to handle button clicks
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    id_parts = query.data.split('_')
    user_id = update.effective_user.id
    original_user_id, message_id = id_parts[1], id_parts[2]

    message = tracked_messages.get(f"{original_user_id}_{message_id}")
    user_votes = message.get("user_votes", [])
    for vote in user_votes:
        if user_id in vote:
            current_vote = vote[user_id]
            if (query.data.startswith("valid") and current_vote == "valid") or \
                    (query.data.startswith("invalid") and current_vote == "invalid"):
                # No need to update counts or display an error message
                return
            # Update vote count based on the button clicked
            if query.data.startswith("valid") and current_vote == "invalid":
                message["valid"] += 1
                message["invalid"] -= 1
                vote[user_id] = "valid"
            elif query.data.startswith("invalid") and current_vote == "valid":
                message["valid"] -= 1
                message["invalid"] += 1
                vote[user_id] = "invalid"
            break
    else:
        new_vote = "valid" if query.data.startswith("valid") else "invalid"
        message["user_votes"].append({user_id: new_vote})
        if new_vote == "valid":
            message["valid"] += 1
        else:
            message["invalid"] += 1

    address = message["address"]
    username = message["username"]

    # Get the original message text shared by the user
    original_text = f"Der Nutzer @{username} meldet eine Hausdurchsuchung an folgender Adresse:\n{address}"
    votes = message['valid'] + message['invalid']
    percent_valid = round(100 * message['valid'] / votes, 2)
    # Edit the original message to show updated vote counts along with the original text
    await query.message.edit_text(
        text=f"{original_text}\n\nValidity: {percent_valid}%\nVotes: {votes}",
        reply_markup=query.message.reply_markup  # Retain the existing reply markup
    )


def run_bot():
    try:
        # Create an Updater object with your bot token
        application = ApplicationBuilder().token(TOKEN).build()
        application.add_handler(CommandHandler('start', start))
        application.add_handler(MessageHandler(filters.LOCATION, handle_location))
        application.add_handler(CallbackQueryHandler(button_click))
        application.run_polling()
    except KeyError:
        print("Error: Environment variable 'PATH_TO_CHANNELS' not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

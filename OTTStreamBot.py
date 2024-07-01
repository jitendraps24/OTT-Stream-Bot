import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from bs4 import BeautifulSoup
import re
from flask import Flask
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def search_imdb(search_query):
    url = f"https://www.imdb.com/find?q={search_query}&s=tt&ref_=fn_al_tt_mr"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        results = []
        for item in soup.select('li.ipc-metadata-list-summary-item'):
            title_tag = item.select_one('a.ipc-metadata-list-summary-item__t')
            year_tag = item.select_one('span.ipc-metadata-list-summary-item__li')
            type_tag = item.select('span.ipc-metadata-list-summary-item__li')[1] if len(
                item.select('span.ipc-metadata-list-summary-item__li')
            ) > 1 else None

            if title_tag and year_tag:
                title = title_tag.text.strip()
                year = year_tag.text.strip()
                result_type = type_tag.text.strip() if type_tag else "Movie"
                imdb_id = re.search(r'/title/(tt\d+)/', title_tag['href'])
                if imdb_id:
                    results.append({
                        'title': title,
                        'year': year,
                        'type': result_type,
                        'imdb_id': imdb_id.group(1)
                    })
        return results
    except requests.RequestException as e:
        logger.error(f"An error occurred while fetching the page: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    return []

def get_movie_poster(imdb_id):
    TMDB_API_KEY = "3b28f2909edf44ced869035f14a0b37a"
    search_url = f"https://api.themoviedb.org/3/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
    response = requests.get(search_url)
    data = response.json()

    if data.get('movie_results'):
        poster_path = data['movie_results'][0].get('poster_path')
    elif data.get('tv_results'):
        poster_path = data['tv_results'][0].get('poster_path')
    else:
        return None

    if poster_path:
        return f"https://image.tmdb.org/t/p/original{poster_path}"
    
    return None

TITLE, SELECTION, SEASON, EPISODE = range(4)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Clear any existing user data
    context.user_data.clear()
    await update.message.reply_text("Welcome! Please enter a movie or TV show title to search:")
    return TITLE

async def handle_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    search_query = update.message.text
    results = search_imdb(search_query)
    if not results:
        await update.message.reply_text("No results found or an error occurred. Please try again.")
        return ConversationHandler.END

    context.user_data['results'] = results
    reply = "Showing up to 8 results:\n"
    for i, result in enumerate(results[:7], 1):
        reply += f"{i}. {result['title']} ({result['year']}) - {result['type']}\n"
    if len(results) > 7:
        reply += "8. Show all results"

    await update.message.reply_text(reply)
    await update.message.reply_text("Enter the number of the result you want to select:")
    return SELECTION

async def handle_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        selection = int(update.message.text)
        results = context.user_data['results']
        if 1 <= selection <= 7:
            selected_result = results[selection - 1]
            context.user_data['selected_result'] = selected_result

            if selected_result['type'] == "TV Series":
                await update.message.reply_text(f"Selected: {selected_result['title']} ({selected_result['year']})")
                await update.message.reply_text("Enter the number of the season you want to watch:")
                return SEASON
            else:
                movie_link = f"https://vidsrc.me/embed/movie/{selected_result['imdb_id']}"
                caption = f"{selected_result['title']} - {selected_result['type']}\n"
                caption += f"Year: {selected_result['year']}\n"
                caption += f"Link: {movie_link}"
                
                poster_url = get_movie_poster(selected_result['imdb_id'])
                if poster_url:
                    await update.message.reply_photo(photo=poster_url, caption=caption)
                else:
                    await update.message.reply_text(caption)
                await update.message.reply_text("Search again /start")
                return ConversationHandler.END

        elif selection == 8 and len(results) > 7:
            reply = "Showing all results:\n"
            for i, result in enumerate(results, 1):
                reply += f"{i}. {result['title']} ({result['year']}) - {result['type']}\n"
            await update.message.reply_text(reply)
            await update.message.reply_text("Enter the number of the result you want to select:")
            return SELECTION
        else:
            await update.message.reply_text("Invalid number. Please try again.")
            return SELECTION
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return SELECTION

async def handle_season(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        season = int(update.message.text)
        context.user_data['season'] = season
        await update.message.reply_text("Enter the number of the episode you want to watch:")
        return EPISODE
    except ValueError:
        await update.message.reply_text("Please enter a valid number for the season.")
        return SEASON

async def handle_episode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        episode = int(update.message.text)
        selected_result = context.user_data['selected_result']
        season = context.user_data['season']
        tv_link = f"https://vidsrc.me/embed/tv/{selected_result['imdb_id']}/{season}/{episode}"
        
        caption = f"{selected_result['title']} ({selected_result['year']}) - {selected_result['type']}\n"
        caption += f"Season: {season}\n"
        caption += f"Episode: {episode}\n"
        caption += f"Link: {tv_link}"
        
        poster_url = get_movie_poster(selected_result['imdb_id'])
        if poster_url:
            await update.message.reply_photo(photo=poster_url, caption=caption)
        else:
            await update.message.reply_text(caption)

        await update.message.reply_text("Search again /start")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Please enter a valid number for the episode.")
        return EPISODE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

def run_flask():
    app = Flask(__name__)

    @app.route('/')
    def home():
        return "Bot is running!"

    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)

def main() -> None:
    logger.info("Starting bot...")
    try:
        # Replace 'YOUR_TOKEN' with your actual bot token
        application = Application.builder().token('7104591151:AAGKQMJhSD9C20mNTkpU1rK1UYgdvbhu0lg').build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_title)],
                SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_selection)],
                SEASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_season)],
                EPISODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_episode)],
            },
            fallbacks=[CommandHandler('cancel', cancel)])

        application.add_handler(conv_handler)
        
        # Add a separate command handler for /start
        application.add_handler(CommandHandler('start', start))

        logger.info("Starting bot polling...")
        # Start the bot polling
        application.run_polling()

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Run the main bot function
    main()

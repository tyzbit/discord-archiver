#!/usr/bin/env python3
import discord
import json
import logging
import pathlib
import requests
import sys
import time
import urllib
from urlextract import URLExtract

archive_api = 'https://web.archive.org'

# https://www.haykranen.nl/2016/02/13/handling-complex-nested-dicts-in-python/
class DictQuery(dict):
  def get(self, path, default = None):
    keys = path.split("/")
    val = None

    for key in keys:
      if val:
        if isinstance(val, list):
          val = [ v.get(key, default) if v else None for v in val]
        else:
          val = val.get(key, default)
      else:
        val = dict.get(self, key, default)

      if not val:
        break;

    return val

class BotState:
  def __init__(self):
    self.load_config()

  def load_config(self):
    '''
    Initializes the bot state by reading it from a file
    '''
    self.current_dir = str(pathlib.Path(__file__).resolve().parent)
    config_file = f'{current_dir}/config.json'
    try:
      with open(config_file, 'r') as read_file:
        try:
          self.config = json.load(read_file)
        except Exception as e:
          logger.error(f'Unable to read config file at {config_file}, {e}')
          sys.exit(1)
    except Exception as e:
      logger.warning(f'Config file not found at {config_file}, exiting')
      sys.exit(1)
    
    # This object keeps track of handled messages.
    self.handled_messages = []

async def send_dm(user=None, text=None, embed=None):
  '''
  Sends a user a DM with the text string provided
  '''
  if not user:
    logger.error(f'send_dm called without user', extra={'guild': 'internal'})
  else:
    logger.debug(msg=f'Sending a message to {user.name}', extra={'guild': 'internal'})
    if embed:
      return await user.send(embed=embed)
    elif text:
      return await user.send(text)
    else:
      logger.error(f'send_dm called without text or embed', extra={'guild': 'internal'})

async def send_to_channel(channel=None, text=None, embed=None):
  '''
  Sends a user a DM with the text string provided
  '''
  if not channel:
    logger.error(f'send_to_channel called without channel', extra={'guild': 'internal'})
  else:
    logger.debug(msg=f'Sending a message to the channel {channel.name}', extra={'guild': channel.guild})
    if embed:
      return await channel.send(embed=embed)
    elif text:
      return await channel.send(text)
    else:
      logger.error(f'send_to_channel called without text or embed', extra={'guild': 'internal'})

async def respond_to_user(message=None, user=None, text=None, embed=None, repeat_react=None):
  '''
  Either sends a DM or replies to a channel depending on config.
  '''
  target = bot_state.config['messageTarget']
  logger.info(f'Sending text {text}, target was {target}, message channel was {message.channel}', extra={'guild': message.guild.id})
  if target == 'user' or message.channel == None:
    if embed is not None:
      await send_dm(user, embed)
    else:
      await send_dm(user, text)
  else:
    if message.id not in bot_state.handled_messages or repeat_react == True:
      if embed is not None:
        await send_to_channel(message.channel, embed)
      else:
        await send_to_channel(message.channel, text)
      bot_state.handled_messages.append(message.id)
    else:
      logger.info(f'Message with ID {message.id} has already been responded to and repeat react not used', extra={'guild': message.guild.id})

def save_page(url):
  '''
  Saves the page using an HTTP get, returns the response object
  '''
  logger.debug(f'Saving page {url}', extra={'guild': 'internal'})
  response = requests.get(archive_api + '/save/' + url, allow_redirects=False)
  logger.debug(f'{url} saved', extra={'guild': 'internal'})
  return response

async def handle_archive_react(extractor, message, user):
  '''
  Finds links in the message that was reacted to and messages archive.org links to the user who reacted
  '''
  logger.info(msg=f'Handling archive react on message {str(message.id)} in channel {str(message.channel.id)}, link for context: https://discord.com/channels/{str(message.guild.id)}/{str(message.channel.id)}/{str(message.id)}', extra={'guild': message.guild.id})
  urls = extractor.find_urls(message.content)
  if urls:
    for url in urls:
      logger.debug(msg=f'URL found: {url}', extra={'guild': message.guild.id})
      wayback_response = requests.get(archive_api + '/wayback/available?url=' + urllib.parse.quote(url)).json()
      logger.debug(msg=f'Wayback response: {str(wayback_response)}', extra={'guild': message.guild.id})
      wayback_url = DictQuery(wayback_response).get('archived_snapshots/closest/url')
      if wayback_url:
        await respond_to_user(message, user, wayback_url)
      else:
        logger.info(msg=f'Wayback did not have the URL {url}, requesting that it be archived', extra={'guild': message.guild.id})
        try:
          response = save_page(url)
        except Exception as e:
          logger.error(msg=f'There was a problem making the request, exception: {e}', extra={'guild': message.guild.id})
          return

        await handle_page_save_request(message, user, url, response, False)

async def handle_repeat_react(extractor, message, user):
  '''
  Rearchives a link and sends the user who reacted a link to the new archive page
  '''
  logger.info(f'Handling repeat react on message {message.id}', extra={'guild': message.guild.id})
  urls = extractor.find_urls(message.content)
  if urls:
    for url in urls:
      try:
        response = save_page(url)
      except Exception as e:
        logger.error(f'Error saving page {url}: {e}', extra={'guild': message.guild.id})
      try:
        await handle_page_save_request(message, user, url, response, True)
      except Exception as e:
        logger.error(f'Error handling page save request: {e}', extra={'guild': message.guild.id})

async def handle_page_save_request(message, user, url, response, repeat_react):
  '''
  Sends a DM if the page save request was successful, if not checks if the page was just saved and sends that.  Otherwise, logs the error
  '''
  if response.status_code not in [302,301]:
    if response.status_code in [523,520]:
      logger.debug(msg=f'Wayback did not proxy the request for url {url}', extra={'guild': message.guild.id})
      await send_dm(user, 'The Internet Archive declined to crawl the link you reacted to.  Sorry.')
    else:
      logger.error(msg=f'Something\'s wrong, we tried to save the page but we were not redirected.  Message ID: {message.id}, URL: {url}', extra={'guild': message.guild.id})
      logger.debug(msg=f'Status code: {response.status_code}', extra={'guild': message.guild.id})
      logger.debug(msg=f'{response.content}', extra={'guild': message.guild.id})
  else:
    try:
      wayback_url = response.headers['Location']
      await respond_to_user(message, user, text=wayback_url, repeat_react=repeat_react)
    except:
      logger.error(msg=f'Unable to extract location from response and send DM. Message ID: {str(message.id)}, URL: {url}', extra={'guild': message.guild.id})
      logger.error(msg=f'Response content: \n' + str(response.content), extra={'guild': message.guild.id})
      logger.error(msg=f'Headers: \n' + str(response.headers), extra={'guild': message.guild.id})
      logger.error(msg=f'Status Code: \n' + str(response.status_code), extra={'guild': message.guild.id})

async def status_command(bot_state, client, message):
  config = bot_state.config
  # only administrators can use this command
  if message.author.id not in config['administratorIds']:
    logger.debug(f'Status command called but {message.author.id} is not in administratorIds', extra={'guild': 'internal'})
  else:
    guild_list = ''
    i = 0
    for guild in client.guilds:
      if i > 0:
        guild_list = f'{guild_list}, {guild.name}'
      else:
        guild_list = f'{guild.name}'

      i = i + 1

    embed = discord.Embed()
    embed.title = 'Archive.org status'
    embed.color = 16753920 # orange
    embed.add_field(name='Guild list', value=guild_list, inline=False)
    embed.add_field(name='Cached messages', value=str(len(client.cached_messages)), inline=False)
    embed.add_field(name='Private messages', value=str(len(client.private_channels)), inline=False)
    embed.add_field(name='Response messages', value=str(len(bot_state.handled_messages)), inline=False)


    await send_dm(message.author, embed=embed)

async def update_activity(bot_state, client, message=None):
  await client.change_presence(
    activity=discord.Activity(
      status=discord.Status.online, 
      type=discord.ActivityType.watching, 
      name=f'{len(client.guilds)} servers'))


def main(bot_state):
  logger.info(msg=f'Starting bot...', extra={'guild': 'internal'})

  discordToken = bot_state.config['discordToken']
  client = discord.Client()

  possible_commands={
    '!archivestatus': 'status_command'
  }

  @client.event
  async def on_ready():
    logger.info(msg=f'{client.user} has connected to Discord!', extra={'guild': 'internal'})
    await update_activity(bot_state, client)
  
  @client.event
  async def on_message(message):
    if message.author == client.user:
      return

    try:
      guild = message.guild.id
    except:
      guild = 'direct'      

    for command in possible_commands:
      if message.content.split(' ')[0] == command:
        function = possible_commands[message.content.split(' ')[0]]
        call_function = globals()[function]
        logger.debug(f'Calling {function}', extra={'guild': guild})
        await call_function(bot_state, client, message)

  @client.event
  async def on_reaction_add(reaction, user):
    if reaction.emoji == '🏛️':
      try:
        await handle_archive_react(extractor, reaction.message, user)
      except Exception as e:
        logger.error(msg=f'Error calling handle_archive_react, exception: {e}', extra={'guild': reaction.message.guild.id})
    elif reaction.emoji == '🔁':
      try:
        await handle_repeat_react(extractor, reaction.message, user)
      except Exception as e:
        logger.error(msg=f'Error calling handle_repeat_react, exception: {e}', extra={'guild': reaction.message.guild.id})

  @client.event
  async def on_guild_join(guild):
    logger.info(f'Joined guild {guild.name}', extra={'guild': guild.id})
    await update_activity(bot_state, client)
  
  @client.event
  async def on_guild_remove(guild):
    logger.info(f'Left guild {guild.name}', extra={'guild': guild.id})
    await update_activity(bot_state, client)

  client.run(discordToken)

if __name__ == '__main__':
  current_dir = pathlib.Path(__file__).resolve().parent

  # Init state
  bot_state = BotState()
  config = bot_state.config

  time.tzset()

  # Set up logging to console and file
  logger = logging.getLogger('bot')
  formatter = logging.Formatter('%(asctime)s - %(guild)s - %(levelname)s - %(message)s')
  if config['logOutput'] == "file" or config['logOutput'] == "both":
    fh = logging.FileHandler(str(current_dir) + '/bot.log')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
  if config['logOutput'] == "stdout" or config['logOutput'] == "both":
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

  # Set loglevel
  level_config = {
    'debug': logging.DEBUG,
    'info': logging.INFO, 
    'warn': logging.WARNING,
    'error': logging.ERROR
  }
  if 'logLevel' in config:
    loglevel = config['logLevel']
    logger.setLevel(level_config[loglevel])
    logger.info(msg=f'Logging set to {config["logLevel"]}...', extra={'guild': 'internal'})
  else:
    logger.setLevel(logging.WARN)
    logger.warn(msg=f'Logging set to warn...', extra={'guild': 'internal'})

  if 'discordToken' not in config:
    logger.error(msg=f'\'discordToken\' is not set in config', extra={'guild': 'internal'})
    sys.exit(1)

  discordToken = config['discordToken']
  extractor = URLExtract()
  main(bot_state)
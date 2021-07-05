#!/usr/bin/env python3
import discord
import json
import logging
import pathlib
import sys
import requests
import urllib
from urlextract import URLExtract

archive_api = 'https://web.archive.org'

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
    self.state={}
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

async def send_dm(user, text):
  logger.debug(msg=f'Sending a message to {user.name}', extra={'guild': 'internal'})
  return await user.send(text)

async def handle_archive_react(extractor, message, user):
  logger.info(msg=f'Handling archive react on message {str(message.id)} in channel {str(message.channel.id)}, link for context: https://discord.com/channels/{str(message.guild.id})/{str(message.channel.id)}/{str(message.id)}', extra={'guild': message.guild.id})
  urls = extractor.find_urls(message.content)
  if urls:
    for url in urls:
      logger.debug(msg='URL found: ' + url, extra={'guild': message.guild.id})
      wayback_response = requests.get(archive_api + '/wayback/available?url=' + urllib.parse.quote(url)).json()
      logger.debug(msg='Wayback response: ' + str(wayback_response), extra={'guild': message.guild.id})
      wayback_url = DictQuery(wayback_response).get('archived_snapshots/closest/url')
      if wayback_url:
        logger.info(msg='Wayback link available, sending to ' + user.name, extra={'guild': message.guild.id})
        await send_dm(user, wayback_url)
      else:
        logger.info(msg=f'Wayback did not have the URL {url}, requesting that it be archived', extra={'guild': message.guild.id})
        try:
          response = save_page(url)
        except Exception as e:
          logger.error(msg=f'There was a problem making the request, exception: {e}', extra={'guild': message.guild.id})
          return

        await handle_page_save_request(message, user, url, response)

async def handle_repeat_react(extractor, message, user):
  logger.info(f'Handling repeat react on message {message.id}', extra={'guild': message.guild.id})
  urls = extractor.find_urls(message.content)
  if urls:
    for url in urls:
      try:
        response = save_page(url)
      except Exception as e:
        logger.error(f'Error saving page {url}: {e}', extra={'guild': message.guild.id})
      try:
        await handle_page_save_request(message, user, url, response)
      except Exception as e:
        logger.error(f'Error handling page save request: {e}', extra={'guild': message.guild.id})

async def handle_page_save_request(message, user, url, response):
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
      location = response.headers['Location']
      logger.info(f'Page archived, sending URL {location} to {user.name}', extra={'guild': message.guild.id})
      await send_dm(user, location)
    except:
      logger.error(msg=f'Location header not found. Message ID: {str(message.id)}, URL: {url}', extra={'guild': message.guild.id})
      logger.error(msg=f'Response content: \n' + str(response.content), extra={'guild': message.guild.id})
      logger.error(msg=f'Headers: \n' + str(response.headers), extra={'guild': message.guild.id})
      logger.error(msg=f'Status Code: \n' + str(response.status_code), extra={'guild': message.guild.id})

def save_page(url):
  logger.debug(f'Saving page {url}', extra={'guild': 'internal'})
  response = requests.get(archive_api + '/save/' + url, allow_redirects=False)
  logger.debug(f'{url} saved', extra={'guild': 'internal'})
  return response

def main(bot_state):
  logger.info(msg='Starting bot...', extra={'guild': 'internal'})

  discordToken = bot_state.config['discordToken']
  client = discord.Client()

  @client.event
  async def on_ready():
    logger.info(msg=f'{client.user} has connected to Discord!', extra={'guild': 'internal'})

  @client.event
  async def on_reaction_add(reaction, user):
    if reaction.emoji == '🏛️':
      try:
        await handle_archive_react(extractor, reaction.message, user)
      except Exception as e:
        logger.error(msg='Error calling handle_archive_react, exception: {e}', extra={'guild': reaction.message.guild.id})
    elif reaction.emoji == '🔁':
      try:
        await handle_repeat_react(extractor, reaction.message, user)
      except Exception as e:
        logger.error(msg='Error calling handle_repeat_react, exception: {e}', extra={'guild': reaction.message.guild.id})

  client.run(discordToken)

if __name__ == '__main__':
  current_dir = pathlib.Path(__file__).resolve().parent

  # Init state
  bot_state = BotState()
  config = bot_state.config

  # Set up logging to console and file
  logger = logging.getLogger('bot')
  fh = logging.FileHandler(str(current_dir) + '/bot.log')
  ch = logging.StreamHandler()
  formatter = logging.Formatter('%(asctime)s - %(guild)s - %(levelname)s - %(message)s')
  fh.setFormatter(formatter)
  ch.setFormatter(formatter)
  if config['logOutput'] == "file" or config['logOutput'] == "both":
    logger.addHandler(fh)
  if config['logOutput'] == "stdout" or config['logOutput'] == "both":
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
    logger.error(msg='\'discordToken\' is not set in config', extra={'guild': 'internal'})
    sys.exit(1)
  discordToken = config['discordToken']
  extractor = URLExtract()
  main(bot_state)
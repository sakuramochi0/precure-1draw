#!/usr/bin/env python3
# precure-1draw.py
#   - Retweet all the tweets with the hashtag and image(including 'http')
#   - Store tweets data
#   - Generate html gallery which show tweets with images
import re
import sys
import os
import difflib
import fcntl
import time
import locale
import datetime
from os import path
from io import BytesIO
import subprocess
import urllib
from collections import deque

from pprint import pprint
from pymongo import Connection
import sqlite3
import pytz
import yaml
from dateutil.parser import parse
import simplejson as json
import requests
from bs4 import BeautifulSoup
from twython import Twython
from twython import TwythonStreamer
from twython import TwythonError
from PIL import Image
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np

# init
def auth():
    '''Authenticate the account and return the twitter instance.'''
    # read app credentials
    with open(setting['credentials']) as f:
        app_key, app_secret, oauth_token, oauth_secret = [x.strip() for x in f]
    t = Twython(app_key, app_secret, oauth_token, oauth_secret)
    return t

def stream_auth():
    '''Authenticate the account and return the twitter stream instance.'''
    # read app credentials
    with open(setting['credentials']) as f:
        app_key, app_secret, oauth_token, oauth_secret = [x.strip() for x in f]
    t = MyStreamer(app_key, app_secret, oauth_token, oauth_secret)
    return t

class MyStreamer(TwythonStreamer):
    def on_success(self, tweet):
        if 'text' in tweet:
            try:
                retweet_and_record(tweet=tweet)
            except TwythonError as e:
                with open('error.log', 'a') as f:
                    f.write(str(e) + '\n')

    def on_error(self, status_code, tweet):
        time.sleep(3)

# load
def auto_retweet_stream():
    '''Retweet all the tweet which have the hash_tag by stream.'''
    stream.statuses.filter(track='#' + setting['hash_tags'][0] + ' ' + setting['triger'])

def auto_retweet_rest(past=3, retweet=True):
    '''Retweet all the tweet which have the hash_tag by rest.'''
    # gather
    max_id=''
    tweets = []
    for i in range(past):
        try:
            res = t.search(q='#' + setting['hash_tags'][0] + ' -RT', count=100, result_type='recent', max_id=max_id)
        except TwythonError as e:
            print('Error occered:', e)
            continue
        res = res['statuses']
        max_id = res[-1]['id_str']
        for tweet in res:
            tweets.append(tweet)
        time.sleep(10)

    # record
    for tweet in reversed(tweets):
        if not has_id(tweet['id']):
            if retweet:
                retweet_and_record(tweet=tweet)
            else:
                retweet_and_record(tweet=tweet, retweet=False)

# retweet & record
def retweet_and_record(tweet=False, id=False, retweet=True, fetch=True, exception=False):
    '''
    Retweet and record the tweet.
    Return a tweet record for other functions' use.
    Otherwise return None to tell them that a fetch failed.
    '''
    # get tweet from twitter or database
    if id:
        if fetch:
            try:
                tweet = t.show_status(id=id)
            except TwythonError as e:
                print('-' * 16)
                if e.error_code == 404:
                    if has_id(id):
                        set_value(id, 'meta.removed', 'deleted')
                        print('404 Not found and marked "deleted":', id)
                        print_tweet(id)
                    else:
                        print('404 Not found and not in database:', id)
                elif e.error_code == 403:
                    if has_id(id):
                        set_value(id, 'meta.removed','locked')
                        print('403 Tweet has been locked and marked "locked":', id)
                        print_tweet(id)
                    else:
                        print('403 Tweet has been locked and not in database:', id)
                elif e.error_code == 429: # API remaining = 0
                    print('api not remaining')
                    return get_tweets('meta.id', id)[0]
                else:
                    print('* Unknown error:', id)
                    print(e)
                    if tweet:
                        pprint(tweet)
    else:
        id = tweet['id']

    if not has_id(id):
        new = True
        if tweet:
            tweet = {'tweet': tweet}
        else:
            return None
    else:
        new = False
        if tweet:
            tweets.update({'meta.id': id}, {'$set': {'tweet': tweet}}, True) # update
        tweet = get_tweets('meta.id', id)[0]

    # excluding filters
    if tweet_filter(tweet, new=new) or exception:
        
        with open(setting['ignores']) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            ignores = yaml.load(f)

        # addpend meta key
        if not 'meta' in tweet:
            tweet['meta'] = {'id': tweet['tweet']['id']}
            
        # get date
        if not 'date' in tweet['meta']:
            tweet['meta']['date'] = get_date(tweet['tweet']['created_at'])
        else:
            date = tweet['meta']['date']

        # exclude a tweet of deny_retweet and set it
        if not 'retweeted' in tweet['meta']:
            tweet['meta']['retweeted'] = False
        if (tweet['tweet']['user']['screen_name'] in ignores['deny_retweet_user']) or (tweet['tweet']['user']['id'] in ignores['deny_retweet_user']):
            tweet['meta']['deny_retweet'] = True
        else:
            tweet['meta']['deny_retweet'] = False
            if retweet and not tweet['meta']['retweeted']:
                try:
                    res = t.retweet(id=tweet['meta']['id'])
                    if res['retweeted']:
                        tweet['meta']['retweeted'] = True
                except TwythonError as e:
                    if e.error_code == 403:
                        print('Double retweet:', tweet['tweet']['id'])
                        tweet['meta']['retweeted'] = True

        # set deny_collection
        if (tweet['tweet']['user']['screen_name'] in ignores['deny_collection_user']) or (tweet['tweet']['user']['id'] in ignores['deny_collection_user']):
            tweet['meta']['deny_collection'] = True
        else:
            tweet['meta']['deny_collection'] = False

        # set exception
        if exception or (not new and tweet['meta']['exception']):
            tweet['meta']['exception'] = True
        else:
            tweet['meta']['exception'] = False
            
        # set removed
        if not 'removed' in tweet['meta']:
            tweet['meta']['removed'] = False
            
        # update database record
        tweets.update({'meta.id': tweet['meta']['id']}, {'$set': tweet}, True)
            
        # get images
        if 'imgs' not in tweet['meta']:
            store_image(tweet['meta']['id'])

        # add labels
        update_labels(tweet['meta']['id'])

        return tweet
        
def including_hash_tag(tweet):
    # 1. if any similar hash_tags in tweet['entities']['hashtags']
    if 'hashtags' in tweet['tweet']['entities']: # tweet has hashtags data
        tweet_tags = tweet['tweet']['entities']['hashtags']
        for tweet_tag in tweet_tags:
            if difflib.get_close_matches(tweet_tag['text'], setting['hash_tags']):
                return True
    # 2. or if any similar hash_tags in tweet['text']
    for match in re.finditer('プリキュア', tweet['tweet']['text']):
        tweet_tag = tweet['tweet']['text'][match.start():match.start()+22]
        if difflib.get_close_matches(tweet_tag, setting['hash_tags']):
            return True

    # otherwise, not including any hash_tag
    return False

def tweet_filter(tweet, new=False):
    '''Filter a spam tweet. If the tweet is spam, return False, otherwise return True.'''
    with open(setting['ignores']) as f:
        ignores = yaml.load(f)

    # allow exception
    if not new:
        if tweet['meta']['exception']:
            return True

    # if ignore_user
    hit = ''
    for user in ignores['ignore_user']:
        if re.search(str(user), str(tweet['tweet']['user']['screen_name'])) or re.search(str(user), str(tweet['tweet']['user']['id'])):
            hit = 'Hit ignore_user "{}":'.format(user)
            return False
    # if ignore_id tweet
    if tweet['tweet']['id'] in ignores['ignore_id']:
        hit = 'Hit ignore_id:'
    # if ignore_url
    elif tweet['tweet']['entities']['urls'] and any([ignore_url in url['expanded_url']
                                                     for ignore_url in ignores['ignore_url']
                                                     for url in tweet['tweet']['entities']['urls']]):
        hit = 'Hit ignore_url:'
    # if fficial retweet
    elif tweet['tweet']['entities']['user_mentions']:
        hit = 'Including user mentions:'
        return False
    # if mention or unofficial retweet
    elif 'retweeted_status' in tweet['tweet']['entities']:
        hit = 'Official retweet:'
    # if including hash_tag which similar to any of the hash_tags
    elif not including_hash_tag(tweet):
        hit = 'Not including any hash_tag:'
    # if including trigger
    elif setting['triger'] not in tweet['tweet']['text']:
        hit = 'Not including triger:'
    # if deleted
    elif not new and tweet['meta']['removed'] == 'deleted':
        hit = 'Already deleted:'
    else:
        # if including ignore_word
        for word in ignores['ignore_word']:
            if re.search(word, tweet['tweet']['text']): 
                hit += 'Hit ignore_word "{}":'.format(word)
    if hit:
        return False
    else:
        return True
    
def record_user(screen_name):
    '''Record all the tweets of the user.'''
    tweets = t.get_user_timeline(screen_name=screen_name, count=100)
    for tweet in tweets:
        retweet_and_record(tweet=tweet, retweet=False)

# image
def store_image(id):
    tweet = get_tweets('meta.id', id)[0]
    urls = []
    if 'extended_entities' in tweet['tweet'] and 'media' in tweet['tweet']['extended_entities']: # tweet has official image
        for url in tweet['tweet']['extended_entities']['media']:
            urls.append((url['media_url'] + ':orig', url['expanded_url']))
    elif 'media' in tweet['tweet']['entities']: # tweet has official image
        for url in tweet['tweet']['entities']['media']:
            urls.append((url['media_url'] + ':orig', url['expanded_url']))
    else:
        for url in tweet['tweet']['entities']['urls']:
            urls.append(url['expanded_url'])

    headers = {}
    imgs = []
    for url in urls:
        if any(['twimg.com' in x for x in url]):
            (img_url, url) = url
        elif 'twitpic.com' in url:
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup.select('#media-main img')[0]['src']
        elif 'photozou.jp' in url:
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup(itemprop='image')[0]['src']
        elif 'p.twipple.jp' in url:
            img_url = url.replace('p.twipple.jp/', 'p.twpl.jp/show/orig/')
        elif 'yfrog.com' in url:
            url = url.replace('yfrog.com', 'twitter.yfrog.com')
            r = requests.get(url)
            soup = BeautifulSoup(r.text)
            url = soup(id='continue-link')[0].a['href']
            r = requests.get(url)
            soup = BeautifulSoup(r.text)
            img_url = soup.select('.main-image a')[0]['href']
        elif 'pixiv' in url:
            headers = {'referer': 'http://www.pixiv.net/'}
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup('img')[1]['src']
        elif 'togetter.com' in url:
            img_url  = False
        elif re.search(r'((jpeg)|(jpg)|(png)|(gif))(.*)$', url):
            img_url = url
        elif re.search(r'twitter.com/.+?/status/.+?/photo', url):
            # check if the photo is animated gif
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup(class_='animated-gif-thumbnail')[0]['src']
            if not img_url:
                img_url = False
        else:
            img_url = False

        if img_url:
            time.sleep(0.5)
            img = requests.get(img_url, headers=headers).content
            
            # guess filename & extenstion
            # In [62]: re.search(r'(.+\.)(jpeg|jpg|png|gif)(.*)$', 'sample.png?extra').groups()
            # Out[62]: ('sample.', 'png', '?extra')
            # In [63]: re.search(r'(.+\.)(jpeg|jpg|png|gif)(.*)$', 'sample.png').groups()
            # Out[63]: ('sample.', 'png', '')
 
            match = re.search(r'(\.(jpeg|jpg|png|gif))', img_url)
            if match:
                filename = ''.join(re.search(r'(.+\.)(jpeg|jpg|png|gif)(.*)$', path.basename(img_url)).group(1,2))
            else:
                ext = Image.open(BytesIO(img)).format.lower()
                filename = path.basename(img_url) + '.' + ext

            # save image
            save_dir = setting['img_dir'] + tweet['tweet']['user']['id_str'] + '/'
            if not path.exists(save_dir):
                os.mkdir(save_dir)
            with open(save_dir + filename, 'wb') as f2:
                f2.write(img)
                print('-' * 16)
                print('downloading image:')
                print('   {}\n-> {}\n-> {}'.format(url, img_url, save_dir + filename))
        else:
            filename = False
            print('No image exists.')

        imgs.append({'url': url, 'img_url': img_url, 'filename': filename})

    # set imgs after save all the imgs loop
    set_value(id, 'meta.imgs', imgs)

def store_image_all():
    with open('store_image.log') as f:
        ids = f.read().split()
    all = tweets.find({'meta.removed': False}).sort([('meta.id', -1)]).count()
    now = 1
    with open('store_image.log', 'a') as f:
        for tweet in tweets.find({'meta.removed': False}).sort([('meta.id', -1)]):
            now += 1
            print('{} / {}'.format(now, all))
            screen_name = tweet['tweet']['user']['screen_name']
            id = tweet['meta']['id']
            print('-' * 8)
            print('https://twitter.com/{}/statuses/{}'.format(screen_name, id))
            if str(id) in ids:
                print('already downloaded', id)
            else:
                store_image(id)
                f.write(str(id) + '\n')

def remove_ignore_tweets():
    with open(setting['ignores']) as f:
        ignores = yaml.load(f)
    for user in ignores['ignore_user']:
        p = re.compile('.*' + str(user) +'.*')
        for i in tweets.find({'$or': [{'tweet.user.screen_name': {'$regex': p}}, {'tweet.user.id': {'$regex': p}}]}):
            print(i['tweet']['user']['screen_name'])
        tweets.remove({'$or': [{'tweet.user.screen_name': p}, {'tweet.user.id': p}]}, multi=True)

def make_symlinks_to_img_dir():
    for tweet in get_tweets():
        src_dir = setting['img_dir'] + tweet['tweet']['user']['id_str']
        dst_dir = setting['img_dir'] + '-' + tweet['tweet']['user']['screen_name']
        if not path.islink(dst_dir) and path.isdir(src_dir):
            os.symlink(os.getcwd() + '/' + src_dir, os.getcwd() + '/' + dst_dir)

# database
def set_value(id, key, val):
    tweets.update({'meta.id': id}, {'$set': {key: val}}, True)

def has_id(id):
    return bool(tweets.find_one({'meta.id': id}))

def destroy_id_tweet(id):
    print_tweet(id)
    tweets.remove({'meta.id': id})
    print('Permanent deleted this tweet')

def get_tweets(key=None, value=None, sort=None):
    # init
    if not sort:
        sort = 'meta.id'
    if not key and not value:
        return tweets.find().sort(sort)
    elif key and value:
        return tweets.find({key: value}).sort(sort)
    else:
        raise Error('Error: Give get_tweets key-value pair')

def copy_database_tweets(date=''):
    # copy database
    con = sqlite3.connect('tweets.sqlite', detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    sqlite3.register_adapter(dict, lambda x: json.dumps(x, ensure_ascii=False))
    sqlite3.register_converter('dict', lambda x: json.loads(x.decode('utf-8')))
    sqlite3.register_adapter(list, lambda x: json.dumps(x, ensure_ascii=False))
    sqlite3.register_converter('list', lambda x: json.loads(x.decode('utf-8')))

    if date:
        query = "select * from tweets where date='{}' order by id".format(date)
    else:
        query = 'select * from tweets order by id'
    for i in con.execute(query):
        if i['removed'] == '0':
            removed = False
        else:
            removed = True
        t = {'meta': {'id': i['id'],
                      'date': i['date'],
                      'imgs': i['imgs'],
                      'labels': i['labels'],
                      'removed': removed,
                      'retweeted': bool(i['retweeted']),
                      'deny_retweet': bool(i['deny_retweet']),
                      'deny_collection': bool(i['deny_collection']),
                      'exception': bool(i['exception'])
                      },
             'tweet': i['tweet']
             }
        tweets.update({'meta.id': i['id']}, {'$set': t}, True)
    print('Copy {} tweets'.format(tweets.count()))

def copy_database_themes():
    # copy themes
    with open(setting['themes']) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        ts = yaml.load(f)

    for num, (date, theme) in enumerate(sorted(ts.items())):
        t = {}
        t['date'] = date
        for k, v in theme.items():
            if v: # only make key non-empty value
                if k == 'num':
                    k = 'work_num'
                    t['num'] = num
                t[k] = v
        print(t)
        themes.update({'date': date}, {'$set': t}, True)
    print('Copy {} themes'.format(themes.count()))

def copy_database():
    copy_database_tweets()
    copy_database_themes()

def print_tweet(id=0, tweet=None):
    if id:
        tweet = tweets.find_one({'meta.id': id})
    print('https://twitter.com/{}/status/{}'.format(tweet['tweet']['user']['screen_name'], tweet['meta']['id']))

def print_all_tweets():
    ts = get_tweets()
    for i in ts:
        print('{} {} {}/{}/{} {}({}) | {}'.format(i['id'], i['date'], i['removed'], i['deny_collection'], i['deny_retweet'], i['tweet']['user']['name'], i['tweet']['user']['screen_name'], i['tweet']['text'][:10]))

def store_image_date(date=''):
    if not date:
        date = get_date()
    tweets = get_tweets('meta.date', date)
    for i, tweet in enumerate(tweets):
        print('-' * 16)
        print('#', i, tweet['meta']['id'])
        print('{} (@{})'.format(tweet['tweet']['user']['name'], tweet['tweet']['user']['screen_name']))
        print(tweet['tweet']['text'])
        if not tweet['meta']['removed']:
            try:
                store_image(tweet['meta']['id'])
            except:
                pass
            time.sleep(1)

def update_date(daily=False, date=''):
    '''
    Update tweets statuses from new to old until api remaining become zero.

    param: daily - if True, append date tweets to the first of que.
    '''
    
    # initialize que file
    if not path.exists(setting['update_date_que']):
        with open(setting['update_date_que'], 'w') as f:
            yaml.dump(deque([]), f)

    # load que file
    with open(setting['update_date_que']) as f:
        ques = yaml.load(f)

    # add daily tweets to the left of ques
    if daily:
        for i in tweets.find({'meta.date': get_date(), 'meta.removed': False, 'meta.deny_collection': False}).sort([('meta.id', -1)]):
            ques.appendleft(i['meta']['id'])
        
    # add the date tweets to the left of ques
    if date:
        for i in tweets.find({'meta.date': date, 'meta.removed': False, 'meta.deny_collection': False}).sort([('meta.id', -1)]):
            ques.appendleft(i['meta']['id'])
        
    # load tweets if there is no que
    if not ques:
        for i in tweets.find({'meta.removed': False, 'meta.deny_collection': False}).sort([('meta.id', -1)]):
            ques.append(i['meta']['id'])
    
    # update tweets while api remaining
    api_remaining = get_show_status_remaining()
    fetch_count = api_remaining[0] - 5
    print('api remaining:', api_remaining[0])
    print('api reset time:', api_remaining[1])
    if fetch_count:
        for i in range(fetch_count):
            id = ques.popleft()
            tweet = tweets.find_one({'meta.id': id})
            retweet_and_record(id=id, retweet=False)
            print_tweet_summary(i, tweet)

        # save que
        with open(setting['update_date_que'], 'w') as f:
            yaml.dump(ques, f)

def print_date_duplicates(date=''):
    '''
    Print duplicate date tweets of the same user
    and ask if it be deleted.
    '''
    if not date:
        date = get_date()

    # for date tweets
    for id in tweets.find({'meta.date': date, 'meta.removed': False, 'meta.deny_collection': False}).distinct('tweet.user.id'):
        user_tweets = tweets.find({'meta.date': date, 'meta.removed': False, 'meta.deny_collection': False, 'tweet.user.id': id}).sort('meta.id')

        # show duplicates
        count = user_tweets.count()
        if count > 1:
            print('-' * 16)
            print('{} (@{}) - {} tweets'.format(user_tweets[0]['tweet']['user']['name'], user_tweets[0]['tweet']['user']['screen_name'], count))
            user_tweets_dict = {}
            for i, tweet in enumerate(user_tweets):
                print_tweet_summary(i, tweet)
                user_tweets_dict[str(i)] = tweet['meta']['id']

            # ask if delete duplicates
            print('-' * 16)
            delete_keys = input('Which tweets should be marked as deleted? (split by spaces for multi delete) > ').split()
            for key in delete_keys:
                id = user_tweets_dict[key]
                set_value(id, 'meta.removed', True)
                print('-' * 16)
                print('deleted tweet:', id)
            
def print_tweet_summary(i, tweet):
    print('-' * 16)
    print('#{}'.format(i), tweet['meta']['date'], 'https://twitter.com/{}/statuses/{}'.format(tweet['tweet']['user']['screen_name'], tweet['meta']['id']))
    print('{} (@{}) [{}/{}]'.format(tweet['tweet']['user']['name'], tweet['tweet']['user']['screen_name'], tweet['tweet']['favorite_count'], tweet['tweet']['retweet_count']))
    print(tweet['tweet']['text'])        
            
# api
def get_search_remaining():
    api = t.get_application_rate_limit_status()['resources']['search']['/search/tweets']
    api_remaining = api['remaining']
    api_reset = datetime.datetime.fromtimestamp(api['reset'])
    return (api_remaining, api_reset)
        
def get_show_status_remaining():
    api = t.get_application_rate_limit_status()['resources']['statuses']['/statuses/show/:id']
    api_remaining = api['remaining']
    api_reset = datetime.datetime.fromtimestamp(api['reset'])
    return (api_remaining, api_reset)

def sleep_until_api_reset():
    remaining, reset = get_show_status_remaining()
    if remaining == 0:
        print('There is no api remaining. Sleep until', reset)
        now = datetime.datetime.now()
        time.sleep((reset - now).seconds + 10)

# generate html
def get_date(time=''):
    '''
    Return a date as begins with 22:50.
    i.e. 2014-07-07 12:00 -> 2014-07-06
         2014-07-07 22:50 -> 2014-07-07

    Why 22:50?
      Because the theme is presented on 22:55,
      so if the threshold were 23:00,
      the theme is granted as the before day's.
    '''
    if not time:
        time = str(datetime.datetime.now().replace(tzinfo=pytz.timezone('Asia/Tokyo')))
    time = parse(time).astimezone(pytz.timezone('Asia/Tokyo'))
    if time.hour <= 21 or (time.hour <= 22 and time.minute < 50):
        time = time.date() - datetime.timedelta(1)
    else:
        time = time.date()
    return str(time)

def read_themes_yaml():
    with open(setting['themes']) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes_yaml = yaml.load(f)
    for theme in themes_yaml:
        print(theme)
        themes.update({'date': theme['date']}, {'$set': theme}, True)
    for theme in themes.find():
        print(theme)

def write_themes_yaml():
    with open(setting['themes'], 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yaml.dump([i for i in themes.find().sort('date')], f, allow_unicode=True)
    
def update_themes():
    '''
    Get a new theme and togetter url from the official account's tweets, 
    and count tweets of the date in the database.
    '''
    res = t.get_user_timeline(screen_name='precure_1draw', count=100)

    # insert new theme of the day
    for tweet in res:
        date = get_date(tweet['created_at'])
        if not themes.find({'date': date}).count():
            match = re.findall('(?:“|”|\'|")(.+?)(?:“|”|\'|")', tweet['text'])
            if match:
                theme = {}
                theme['theme'] = ' / '.join(match)
                theme['theme_en'] = ''
                theme['category'] = ['uncategorized']
                themes.update({'date': date}, {'$set': theme}, True)
                #t.retweet(id=tweet['id']) # retweet a official theme tweet
        else:
            break

    # update togetter url
    for i in themes.find({'togetter': {'$exists': False}}).sort('date'):
        date = i['date']
        tweet = tweets.find_one({'meta.date': date, 'tweet.user.screen_name': 'precure_1draw'})
        if tweet:
            togetter = tweet['tweet']['entities']['urls'][0]['expanded_url']
            themes.update({'date': date}, {'$set': {'togetter': togetter}}, True)

    # count event number and work number
    for num, theme in enumerate(themes.find().sort('date')):
        work_num = tweets.find({'meta.date': theme['date'], 'meta.removed': False, 'meta.deny_collection': False}).count()
        themes.update({'date': theme['date']}, {'$set': {'num': num, 'work_num': work_num}}, True)

    # count user number
    for date in themes.distinct('date'):
        if date == '0-misc':
            themes.update({'date': date}, {'$set': {'user_num': 0}})
        else:
            user_num = len(tweets.find({'meta.date': {'$lte': date}, 'meta.deny_collection': False, 'meta.removed': False}).distinct('tweet.user.id'))
            themes.update({'date': date}, {'$set': {'user_num': user_num}}, True)

    write_themes_yaml()

def update_users():
    user_ids = tweets.find({'meta.deny_collection': False, 'meta.removed': False, 'tweet.user.screen_name': {'$not': re.compile(r'^precure_1draw$')}}).distinct('tweet.user.id')
    users.remove()
    for user_id in user_ids:
        user = {}
        tweet = tweets.find({'tweet.user.id': user_id}, {'meta.id': {'$slice': -1}})[0] # get the latest tweet
        num = tweets.find({'tweet.user.id': user_id, 'meta.removed': False}).count()
        cls = num // 10 * 10
        users.update({'id': user_id }, {'$set': {'id': user_id, 'num': num, 'class': cls, 'user': tweet['tweet']['user']}}, True)

def update_infos():
    with open(setting['info_file']) as f:
        infos_yaml = yaml.load(f)
    for id, info in enumerate(reversed(infos_yaml)):
        info_dict = {}
        info_dict['id'] = id
        for k, v in info.items():
            info_dict[k] = v
        print(info_dict)
        infos.update({'id': id}, info_dict, True)

def print_first_participants():
    with open(setting['themes'], 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        themes = yaml.load(f)

        users = []
        for date in sorted(themes):
            if date != '0-misc':
                print('-'*8)
                print(date)
                tweets = get_tweets('meta.date', date)
                old = set(users)
                users.extend([t['tweet']['user']['id'] for t in tweets])
                new = set(users) - old
                print(new)
                for text in [tweet['tweet']['text'] for tweet in tweets if tweet['tweet']['user']['id'] in new]:
                    print('*', text)
                # print(set(users))
                print(len(new))
                
def get_user_work_number(id):
    '''Return the number of the id tweet work of the user.'''
    screen_name = get_tweets('meta.id', id)[0]['tweet']['user']['screen_name']
    tweets = get_tweets('tweet.user.screen_name', screen_name)
    for num, tweet in enumerate(tweets):
        if tweet['meta']['id'] == id:
            return num + 1

def update_labels(id, force=False):
    '''Update labels of the database which is used at each tweet's header.'''
    tweet = get_tweets('meta.id', id)[0]
    lucky_nums = list(range(10, 1001, 10))
    labels = []

    if 'labels' in tweet['meta'] and not force:
        return
    
    # lucky number
    num = get_user_work_number(id)
    if num == 1:
        labels.append('初参加')
    else:
        for lucky_num in lucky_nums:
            if num == lucky_num:
                labels.append(str(lucky_num))

    # gif
    if 'imgs' in tweet['meta']:
        if '/tweet_video_thumb/' in str(tweet['meta']['imgs'][0]['img_url']): # str() for bool value
            labels.append('GIF')

    if not labels:
        labels = ['none']
        
    print('set labels:',labels)
    set_value(id, 'meta.labels', labels)

def update_labels_all():
    user_ids = tweets.distinct('tweet.user.id')
    lucky_nums = list(range(10, 1001, 10))

    for user_id in user_ids:
        print('-' * 16)
        print('Update labels of user:', tweets.find_one({'tweet.user.id': user_id})['tweet']['user']['screen_name'])
        user_tweets = tweets.find({'tweet.user.id': user_id, 'meta.removed': False}).sort('meta.id')
        
        for num, tweet in enumerate(user_tweets):
            labels = []
            num += 1
            print_tweet_summary(num, tweet)

            # lucky number
            if num == 1:
                labels.append('初参加')
            else:
                if num in lucky_nums:
                    labels.append(str(num))
           
            # gif
            if not 'imgs' in tweet['meta']:
                retweet_and_record(id=tweet['meta']['id'], retweet=False)
                print('not imgs')
                
            imgs = tweet['meta']['imgs']
            if imgs and '/tweet_video_thumb/' in str(imgs[0]['img_url']): # str() for bool value
                labels.append('GIF')
           
            if not labels:
                labels = ['none']
                
            print(tweet['meta']['id'], 'Set labels:', labels)
            set_value(tweet['meta']['id'], 'meta.labels', labels)
        
def chart():
    def col_list(key):
        return [i[key] for i in themes.find().sort('num') if i['date'] != '0-misc']

    days = col_list('num')
    nums = col_list('work_num')
    user_nums = col_list('user_num')
     
    # ax1: works num, ax2: user num
    fig, ax = plt.subplots()

    ax1 = plt.axes()
    ax2 = ax1.twinx()
     
    ax1.plot(days, user_nums, '.-', color='lightsteelblue', linewidth=2)
    ax2.plot(days, nums, '.-', color='palevioletred', linewidth=2)

    fig.autofmt_xdate()

    # set limit
    ax1.set_xlim(0, max(days) + 1)
    ax1.set_ylim(0, max(user_nums) + 30)
    ax2.set_ylim(0, max(nums) + 15)

    # set locator
    ax1.xaxis.set_major_locator(plt.MultipleLocator(10))
    ax1.yaxis.set_major_locator(plt.MultipleLocator(100))
    ax2.xaxis.set_major_locator(plt.MultipleLocator(10))
    ax2.yaxis.set_major_locator(plt.MultipleLocator(25))

    # set grid
    ax2.grid(True)

    # label
    fp = FontProperties(fname='Hiragino Sans GB W3.otf')
    ax1.set_xlabel('回数', fontproperties=fp)
    ax1.set_ylabel('累計参加者数', fontproperties=fp)
    ax2.set_ylabel('作品数', fontproperties=fp)
     
    # legend
    p1 = plt.Rectangle((0, 0), 1, 1, fc="lightsteelblue")
    p2 = plt.Rectangle((0, 0), 1, 1, fc="palevioletred")
    ax1.legend([p1, p2], ['累計参加者数', '作品数'], loc='upper left', prop=fp)

     
    #plt.title('作品数の変化', fontproperties=fp)
    plt.savefig(setting['html_dir'] + 'chart.svg')
    plt.savefig('static/chart.svg')

    # en
    ax1.set_xlabel('#', fontproperties=fp)
    ax1.set_ylabel('Total perticipants')
    ax2.set_ylabel('Works')
    ax1.legend([p1, p2], ['Total perticipants', 'Works'], loc='upper left')
    plt.savefig(setting['html_dir'] + 'chart-en.svg')
    plt.savefig('static/chart-en.svg')

def fav_plus_rt(tweet):
    fav = tweet['tweet']['favorite_count']
    rt = tweet['tweet']['retweet_count']
    if fav + rt > 150:
        return 150
    else:
        return fav + rt

def generate_rank_html():
    '''Generate user rank pages.'''
    with open(setting['rank_users']) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        screen_names = yaml.load(f)
    
    for screen_name in screen_names:
        favs = {}
        imgs = []
        for theme in themes.find().sort([('date', -1)]):
            user_tweet = tweets.find_one({'meta.date': theme['date'], 'tweet.user.screen_name': screen_name})
            if not user_tweet:
                continue
            favs[theme['date']] = [fav_plus_rt(tweet) for tweet in tweets.find({'meta.date': theme['date']})]
            user_fav = fav_plus_rt(user_tweet)
         
            fig, ax = plt.subplots()
            n, bins, patches = plt.hist(favs[theme['date']], color='skyblue', bins=50)
            idx = (np.abs(bins - user_fav)).argmin()
            idx = min(idx, len(patches)-1)
            #print(idx, patches)
            if patches[idx].get_height():
                patches[idx].set_facecolor('palevioletred')
            elif patches[idx+1].get_height():
                patches[idx+1].set_facecolor('palevioletred')
            else:
                patches[idx-1].set_facecolor('palevioletred')
            fp = FontProperties(fname='Hiragino Sans GB W3.otf')
            ax.set_xlabel('Fav+RT', fontproperties=fp)
            ax.set_ylabel('人数', fontproperties=fp)
            save_dir = setting['img_dir'] + user_tweet['tweet']['user']['id_str']
            if not path.exists(save_dir):
                os.mkdir(save_dir)
            filename = theme['date'] + '.svg'
            plt.savefig(save_dir +  '/' + filename)
            plt.close()
         
            total = len(favs[theme['date']])
            rank = sorted(favs[theme['date']], reverse=True).index(user_fav)
            percent = int((rank / total) * 100)
         
            imgs.append('''<p style="margin-left: 4em;">[{}] {} - {}<br>Fav+RT: {}<br>Rank: {} / {} ({}%)</p>
            <img src="{img}" style="max-width: 500px;">
            <img id="{src}" src="{src}">'''.format('-'.join(user_tweet['meta']['labels']), theme['date'], theme['theme'], user_fav, rank+1, total, percent, src='{{% static "precure_1draw_collections/img/{}/{}" %}}'.format(user_tweet['tweet']['user']['id'], filename), img='{{% static "precure_1draw_collections/img/{}/{}" %}}'.format(user_tweet['tweet']['user']['id'], user_tweet['meta']['imgs'][0]['filename'])))
     
# admin
def handle_admin_actions():
    with open(setting['admin_actions'], 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        actions = yaml.load(f)

        for time, item in actions.items():
            if not item['done']:
                action = item['action']
                args = item['args']
                id = item['id']
                if action == 'rotate':
                    action_rotate(id, args['angle'])
                elif action == 'remove':
                    action_remove(id)
                elif action == 'move':
                    action_move(id, args['dest'])
                elif action == 'deny_collection_user':
                    action_deny_collection_user(id)
                elif action == 'ignore_user':
                    action_ignore_user(id)
        for time, item in actions.items():
             item['done'] = True
        f.seek(0)
        f.truncate()
        yaml.dump(actions, f)
        
    generate_admin_history_html()

def generate_admin_history_html():
    with open(setting['admin_actions']) as f:
        actions = yaml.load(f)
        tr = [actions_history_tr(time, item) for time, item in reversed(sorted(actions.items()))]
        tr = '\n\n'.join(tr)

        with open(setting['admin_actions_history_html']) as f:
            template = f.read()
        html = template.format(tr=tr, last_update=last_update())

        with open(setting['html_dir'] + 'date/admin-history.html', 'w') as f:
            f.write(html)
                
def actions_history_tr(time, actions):
    id = actions.pop('id')
    action = actions.pop('action')
    if action == 'rotate':
        if actions['args']['angle'] == 'left':
            action = '反時計回りに90°回転する'
        elif actions['args']['angle'] == 'right':
            action = '時計回りに90°回転する'
    elif action == 'remove':
        action = 'まとめから削除する'
    elif action == 'ignore_user':
        action = '迷惑ユーザーに追加する'
    elif action == 'move':
        with open(setting['themes']) as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            themes = yaml.load(f)
        date = get_tweets('meta.id', id)[0]['date']
        action = '「{} - {}」へ移動する'.format(actions['args']['dest'], themes[actions['args']['dest']]['theme'])
        
    args = ['{arg}: {val}'.format(arg=arg, val=val) for arg, val in actions.items()]
    args = ' / '.join(args)
    time = time.strftime('%Y年%m月%d日 %H:%M')
    user = get_tweets('meta.id', id)[0]['tweet']['user']['screen_name']
    admin = actions['admin']
    if actions['done']:
        done = '実行済み'
    else:
        done = '未完了'
    tr = '''<tr>
  <td class="time">{time}</td>
  <td class="id"><a href="https://twitter.com/{user}/status/{id}"><i class="fa fa-square fa-lg" style="color: skyblue" title="ツイートページを見る"></i></a></td>
  <td class="action">{action}</td>
  <td class="user">{admin}</td>
  <td class="done">{done}</td>
</tr>'''.format(time=time, user=user, id=id, action=action, admin=admin, done=done)
    return tr

# global action
def action_add_exception(id):
    '''Add a tweet by id as a exception.'''
    retweet_and_record(id=id, retweet=False, exception=True)
    
# local action
def action_rotate(id, angle):
    '''Rotate the image of the tweet.'''
    if angle == 'left':
        angle = '-90'
    elif angle == 'right':
        angle = '90'

    tweet = get_tweets('meta.id', id)[0]
    img_path = setting['img_dir'] + tweet['tweet']['user']['id_str'] + '/' + tweet['meta']['imgs'][0]['filename']
    subprocess.call(['mogrify', '-rotate', angle, img_path])

def action_remove(id, un=False):
    '''Remove the tweet from the collection.'''
    if not un:
        set_value(id, 'meta.removed', 'deleted')
    else:
        set_value(id, 'meta.removed', False)
    date = get_tweets('meta.id', id)[0]['date']

def action_move(id, new_date, un=False):
    '''Move the tweet to the other page.'''
    old_date = get_tweets('meta.id', id)[0]['date']
    set_value(id, 'meta.date', new_date)
    
def action_deny_collection_user(id, un=False):
    '''Add the user of the tweet to deny_collection_user.'''
    with open(setting['ignores'], 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ignores= yaml.load(f)

        tweet = get_tweets('meta.id', id)[0]
        if not un:
            ignores['deny_collection_user'].append(tweet['tweet']['user']['id'])
            ignores['deny_collection_user'].append(tweet['tweet']['user']['screen_name'])
        else:
            ignores['deny_collection_user'].remove(tweet['tweet']['user']['id'])
            ignores['deny_collection_user'].remove(tweet['tweet']['user']['screen_name'])

        f.seek(0)
        f.truncate()
        yaml.dump(ignores, f, allow_unicode=True)

def action_ignore_user(id, un=False):
    '''Add the user of the tweet to deny_collection_user.'''
    with open(setting['ignores'], 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ignores= yaml.load(f)

        tweet = get_tweets('meta.id', id)[0]
        if not un:
            ignores['ignore_user'].append(tweet['tweet']['user']['id'])
            ignores['ignore_user'].append(tweet['tweet']['user']['screen_name'])
        else:
            ignores['ignore_user'].remove(tweet['tweet']['user']['id'])
            ignores['ignore_user'].remove(tweet['tweet']['user']['screen_name'])

        f.seek(0)
        f.truncate()
        yaml.dump(ignores, f, allow_unicode=True)

def import_ids(file):
    with open(file) as f:
        ids = f.read().split()
    for i, id in enumerate(ids):
        print('-' * 16)
        print('import:', id)
        tweet = retweet_and_record(id=id, retweet=False)
        print_tweet_summary(i, tweet)

def api_get_tweets(screen_name=''):
    """
    Get user timeline as much as possible.
    Return: list of tweets
    """
    tweets = []
    max_id = None
    duplicate = 0
    for i in range(1, 30):
        res = t.get_user_timeline(screen_name=screen_name, count=200, max_id=max_id)
        tweets.extend(res)
        if max_id == res[-1]['id']:
            duplicate += 1
            print('duplicate', duplicate)
            if duplicate > 1:
                break
        else:
            duplicate = 0
            max_id = res[-1]['id']
            print('{}回目 max_id: {}'.format(i, max_id))
    for tweet in tweets:
        if '#' in tweet['text']:
            print(tweet['text'])
        
def get_tweets_from_precure_1draw():
    tweets = []
    max_id = None
    duplicate = 0
    for i in range(1, 30):
        res = t.get_user_timeline(screen_name='precure_1draw', count=200, max_id=max_id)
        tweets.extend(res)
        if max_id == res[-1]['id']:
            duplicate += 1
            print('duplicate', duplicate)
            if duplicate > 1:
                break
        else:
            duplicate = 0
            max_id = res[-1]['id']
            print('{}回目 max_id: {}'.format(i, max_id))
    with open('tweets_of_precure_1draw.json', 'w') as f:
        json.dump(tweets, f)
        
def show_status(id):
    if has_id(id):
        print_tweet(id)
    else:
        tweet = t.show_status(id=id)
        print_tweet(tweet=tweet)

if __name__ == '__main__':

    # run the given function
    if len(sys.argv) < 3:
        print('Usage:', sys.argv[0], 'genre_name func()')
    elif len(sys.argv) == 3:
        # load setting file
        genre = sys.argv[1]
        with open('settings.yaml') as f:
            setting = yaml.load(f)[genre]

        # prepend twitter object
        t = auth()
        stream = stream_auth()
    
        tweets = eval('Connection().' + genre + '_1draw_collections.tweets')
        themes = eval('Connection().' + genre + '_1draw_collections.themes')
        users = eval('Connection().' + genre + '_1draw_collections.users')
        infos = eval('Connection().' + genre + '_1draw_collections.infos')
        eval(sys.argv[2])


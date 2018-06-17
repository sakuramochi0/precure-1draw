#!/usr/bin/env python3
import re
import sys
import os
import difflib
import fcntl
import time
import locale
import datetime
import os
from io import BytesIO
import subprocess
import urllib
from collections import deque
import base64
import argparse

from pprint import pprint
from get_mongo_client import get_mongo_client
import pytz
import yaml
from dateutil.parser import parse
import simplejson as json
import requests
from bs4 import BeautifulSoup
from PIL import Image
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
from googleapiclient.discovery import build
from get_tweepy import *

def save_tweet(must_retweet=True, ids=None, screen_names=None):
    """Retweet tweets which have the hash_tag by REST API.

    Args:
        must_retweet:
            Save the tweet but does not retweet it if False.
        ids:
            Gets tweets of the ids not tag search results.
    """
    if ids:
        ts = api.statuses_lookup(ids)
    elif screen_names:
        ts = []
        for sn in screen_names:
            ts += [t for t in tweepy.Cursor(api.user_timeline,
                                           screen_name=sn,
                                           count=200,
                                           tweet_mode='extended').items(2000)]
        ts = [t for t in map(assign_text_to_full_text, ts) if is_right_tweet(t)]
    else:
        ts = [t for t in tweepy.Cursor(api.search,
                                       q='#' + setting['hash_tag'] + ' -RT',
                                       count=200,
                                       tweet_mode='extended').items(500)]
        ts = list(map(assign_text_to_full_text, ts))
    for t in reversed(ts):
        if is_right_tweet(t):
            record(t)
            store_image(t.id)
            if must_retweet:
                retweet(t)

def assign_text_to_full_text(t):
    t.text = t.full_text
    t._json['text'] = t._json['full_text']
    return t

def is_right_tweet(t):
    """
    Check whether the tweet is to be recorded to database and retweeted.
    """
    return not has_id(t.id) and is_not_spam(t)
            
def record(t):
    """
    Record a tweet to database.
    """
    if not has_id(t.id):
        doc = make_doc(t)
        tweets.insert_one(doc)

def retweet(t):
    """
    Retweet the tweet.
    """
    try:
        res = t.retweet()
        id = res.id
    except tweepy.TweepError as e:
        if e.api_code == 327: # already retweeted
            id = t.id
        else:
            raise
    tweets.update_one({'_id': t.id},
                      {'$set': {
                          'meta.retweeted': True,
                          'meta.retweet_id': id,
                      }})

def make_doc(t):
    """
    Make MongoDB doc object from the tweet.
    """
    time = parse(t._json['created_at']).astimezone(pytz.timezone('Asia/Tokyo'))
    doc = {
        '_id': t.id,
        'meta': {
            'time': time,
            'date': get_date(time),
            'retweeted': False,
            'removed': False,
            'deny_collection': False,
            'deny_retweet': False,
            'exception': False,
            'labels': ['none'],
            'imgs': [],
        },
        'tweet': t._json,
    }
    return doc

def get_date(time):
    """
    Get tweeting date of the tweet.
    """
    threshold_time = (parse(setting['start_time']) - datetime.timedelta(minutes=30)).time()
    if time.time() < threshold_time:
        return time.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None) - datetime.timedelta(days=1)
    else:
        return time.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

def get_date_pripara_prpr(time):
    # first threshold - on wednesday
    if parse('wed').weekday() == time.weekday():
        if time.time() < parse('21:00').time():
            delta = 4
        else:
            delta = 0

    # second threshold - on saturday
    if parse('sat').weekday() == time.weekday():
        if time.time() < parse('21:00').time():
            delta = 3
        else:
            delta = 0

    # first span - from thu to fri
    if parse('wed').weekday() < time.weekday() < parse('sat').weekday():
        delta = time.weekday() - parse('wed').weekday()

    # second span - from sun to tue
    if parse('sat').weekday() < time.weekday():
        delta = time.weekday() - parse('sat').weekday()
    elif time.weekday() < parse('wed').weekday():
        delta = time.weekday() + 2

    date = time.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    date -= datetime.timedelta(days=delta)
    return date

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
                tweet = api.get_status(id=id)
                if has_id(id):
                    set_value(id, 'meta.removed', False)
                
            except TweepError as e:
                print('-' * 16)
                if e.api_code == 404:   # tweet was deleted
                    if has_id(id):
                        set_value(id, 'meta.removed', 'deleted')
                        print('404 Not found and marked "deleted":', id)
                        print_tweet(id)
                        return None
                    else:
                        print('404 Not found and not in database:', id)
                elif e.api_code == 403:   # accound has been locked
                    if has_id(id):
                        set_value(id, 'meta.removed','locked')
                        print('403 Tweet has been locked and marked "locked":', id)
                        print_tweet(id)
                        return None
                    else:
                        print('403 Tweet has been locked and not in database:', id)
                        return None
                elif e.api_code == 429: # API remaining = 0
                    print('api not remaining')
                    return get_tweets('_id', id)[0]
                else:
                    print('* Unknown error:', id)
                    print(e)
                    if tweet:
                        pprint(tweet)
                    return None
    else:
        id = tweet['id']

    if not has_id(id):
        new = True
        if tweet:
            tweet = {'tweet': tweet}
    else:
        new = False
        if tweet:
            tweets.update_one({'_id': id}, {'$set': {'tweet': tweet}}, True)
        tweet = get_tweets('_id', id)[0]

    # excluding filters
    if is_not_spam(tweet, new=new) or exception:
        
        with open(setting['ignores']) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            ignores = yaml.load(f)

    return tweet

def including_hash_tag(t):
    """
    Check if the tweet includes the hashtag.
    """
    if 'hashtags' in t.entities: # tweet has hashtags data
        if any(filter(lambda tag: tag['text'] == setting['hash_tag'], t.entities['hashtags'])):
            return True
    print('no including hash_tag')
    return False

def is_not_spam(t):
    """
    Check the tweet is not a spam.
    """

    spam = ''
    # if ignore_id tweet
    if t.id in ignores['ignore_id']:
        spam = 'Hit ignore_id:'
    # if ignore_url
    elif t.entities['urls'] and any([ignore_url in url['expanded_url']
                                                     for ignore_url in ignores['ignore_url']
                                                     for url in t.entities['urls']]):
        spam = 'Hit ignore_url:'
    # if official retweet
    elif t.entities['user_mentions']:
        spam = 'Including user mentions:'
    # if mention
    elif 'retweeted_status' in t.entities:
        spam = 'Official retweet:'
    # if including hash_tag which similar to any of the hash_tags
    elif not including_hash_tag(t):
        spam = 'Not including any hash_tag:'
    # if including image
    elif 'http' not in t.text:
        spam = 'Not including http:'
        print(t.text)
    # if ignore_user
    elif t.user.id in ignores['ignore_user'] or t.user.screen_name in ignores['ignore_user']:
        spam = 'Hit ignore_user "{}":'.format(t.user.screen_name)
    # not in white list users
    elif (t.user.screen_name not in ignores['white_user']) \
         and (t.user.id not in  ignores['white_user']):
        # if recently created account
        if t.user.created_at > datetime.datetime.now() - datetime.timedelta(weeks=1):
            spam = 'Hit too recently created:'
        # if unsafe images
        # elif tweets.find({'tweet.user.id': t.user.id}).count() == 0 \
        #      and is_unsafe_image(t):
        #     add_ignore_users(t.user.id)
        #     cancel_user_retweet(t.user.id)
        #     spam = 'Hit unsafe image:'
    # if including ignore_word
    else:
        for word in ignores['ignore_word']:
            if re.search(word, t.text): 
                spam += 'Hit ignore_word "{}":'.format(word)
    if spam:
        print('[is_not_spam()] hit spam by reason: {reason}'.format(reason=spam))
        print_tweet(t)
        return False
    else:
        return True
    
def check_new_ignore_user_list():
    """
    Check new ignore users and add them ignore list.
    """
    ls = api.get_list(owner_screen_name=setting['rt_account'], slug='list')
    user_ids = get_list_members(list_id=ls.id)
    user_ids = add_ignore_users(user_ids)
    cancel_user_retweet(user_ids)

def get_list_members(list_id):
    """
    Get ids of members in `list_id` list.
    """
    ids = [u.id for u in tweepy.Cursor(api.list_members, list_id=list_id, count=100).items()]
    return ids

def add_ignore_users(user_ids):
    """
    Add `user_id`'s user to ignore list.
    """
    if not type(user_ids) in (set, list):
        user_ids = [user_ids]
        
    with open(setting['ignores'], 'r+') as f:
        # Read file
        fcntl.flock(f, fcntl.LOCK_SH)
        ignores = yaml.load(f)

        # Add a user's screen_name and id
        new_ignore_user_ids = []
        for user_id in user_ids:
            if not user_id in ignores['ignore_user']:
                user = api.get_user(id=user_id)
                ignores['ignore_user'].append(user.screen_name)
                ignores['ignore_user'].append(user_id)
                new_ignore_user_ids.append(user_id)

        # Write file
        f.seek(0)
        f.truncate()
        yaml.dump(ignores, f, allow_unicode=True)

    # Return new added users
    return new_ignore_user_ids

def cancel_user_retweet(user_ids):
    """
    Destroy all the past retweets by the users.
    """
    if not type(user_ids) in [set, list]:
        user_ids = [user_ids]
    for user_id in user_ids:
        cancel_tweets = tweets.find({'tweet.user.id': user_id})
        for cancel_tweet in cancel_tweets:
            try:
                t = api.get_status(id=cancel_tweet['_id'])
                if t.retweeted and 'retweet_id' in cancel_tweet['meta']:
                    api.destroy_status(id=cancel_tweet['meta']['retweet_id'])
                    tweets.remove({'_id': cancel_tweet['_id']})
            except tweepy.TweepError as e:
                # Tweet removed
                if e.api_code == 404:
                    tweets.remove({'_id': cancel_tweet['_id']})
                else:
                    raise

def record_user(screen_name):
    """
    Record all the tweets of the user.
    """
    ts = api.user_timeline(screen_name=screen_name, count=100, tweet_mode='extended')
    ts = map(assign_text_to_full_text, ts)
    for t in ts:
        save_tweet(t, retweet=False)

def is_unsafe_image(t):
    """
    Detect whether the tweet includes unsafe images by Google Cloud Vision API.
    """
    print_tweet(t)

    # Get image url from tweet

    # The tweet has official images
    if getattr(t, 'extended_entities', False) and 'media' in t.extended_entities:
        urls = [media['media_url_https'] for media in t.extended_entities['media']]
    else:
        # if not images, pass the check
        return False

    # Request for Google Cloud Vision API
    for url in urls:
        r = requests.get(url)
        image = base64.b64encode(r.content).decode('UTF-8')
        body = {
            "requests": [
                {
                    'image': {
                        'content': image,
                    },
                    "features": [
                        {
                            "type": "SAFE_SEARCH_DETECTION",
                        },
                    ]
                },
            ]
        }
        res = vision.images().annotate(body=body).execute()

        # Chack unsafe possibility
        annotation = res['responses'][0]['safeSearchAnnotation']
        annotation.pop('spoof')
        print(annotation)
        unsafe_possible = any([possibility in ['LIKELY', 'VERY_LIKELY']
                               for possibility in annotation.values()])
        if unsafe_possible:
            print('Found unsafe image:')
            return True

    return False

def store_image(id):
    doc = tweets.find_one(id)
    tweet = doc['tweet']
    urls = []
    if 'extended_entities' in tweet \
       and 'media' in tweet['extended_entities']:
        # if tweet has official image
        for url in tweet['extended_entities']['media']:
            urls.append((url['media_url_https'] + ':orig', url['expanded_url']))
    elif 'media' in tweet['entities']:
        # if tweet has official image
        for url in tweet['entities']['media']:
            urls.append((url['media_url_https'] + ':orig', url['expanded_url']))
    else:
        for url in tweet['entities']['urls']:
            urls.append(url['expanded_url'])

    headers = {}
    imgs = []
    for url in urls:
        if any(['twimg.com' in x for x in url]):
            (img_url, url) = url
        elif 'twitpic.com' in url:
            soup = BeautifulSoup(requests.get(url).text, 'lxml')
            img = soup.select('#media-main img')
            if not img:
                img_url = False
            else:
                img_url = img[0]['src']
            
        elif 'photozou.jp' in url:
            soup = BeautifulSoup(requests.get(url).text, 'lxml')
            img_url = soup(itemprop='image')[0]['src']
        elif 'p.twipple.jp' in url:
            img_url = url.replace('p.twipple.jp/', 'p.twpl.jp/show/orig/')
        elif 'yfrog.com' in url:
            url = url.replace('yfrog.com', 'twitter.yfrog.com')
            r = requests.get(url)
            soup = BeautifulSoup(r.text, 'lxml')
            url = soup(id='continue-link')[0].a['href']
            r = requests.get(url)
            soup = BeautifulSoup(r.text, 'lxml')
            img_url = soup.select('.main-image a')[0]['href']
        elif 'pixiv' in url:
            headers = {'referer': 'http://www.pixiv.net/'}
            soup = BeautifulSoup(requests.get(url).text, 'lxml')
            img_url = soup('img')[1]['src']
        elif 'togetter.com' in url:
            img_url  = False
        elif re.search(r'((jpeg)|(jpg)|(png)|(gif))(.*)$', url):
            img_url = url
        elif re.search(r'twitter.com/.+?/status/.+?/photo', url):
            # check if the photo is animated gif
            soup = BeautifulSoup(requests.get(url).text, 'lxml')
            img_url = soup(class_='animated-gif-thumbnail')[0]['src']
            if not img_url:
                img_url = False
        else:
            img_url = False

        imgs.append({'url': url, 'img_url': img_url})

    # set imgs after save all the imgs loop
    tweets.update_one({'_id': id}, {'$set': {'meta.imgs': imgs}})
    return imgs
    
def remove_ignore_tweets():
    with open(setting['ignores']) as f:
        ignores = yaml.load(f)
    for user in ignores['ignore_user']:
        p = re.compile('.*' + str(user) +'.*')
        for i in tweets.find({'$or': [{'tweet.user.screen_name': {'$regex': p}}, {'tweet.user.id': {'$regex': p}}]}):
            print(i['tweet']['user']['screen_name'])
        tweets.delete_one({'$or': [{'tweet.user.screen_name': p}, {'tweet.user.id': p}]}, multi=True)

def make_symlinks_to_img_dir():
    for tweet in get_tweets():
        src_dir = setting['img_dir'] + t['tweet']['user']['id_str']
        dst_dir = setting['img_dir'] + '-' + tweet['tweet']['user']['screen_name']
        if not os.path.islink(dst_dir) and os.path.isdir(src_dir):
            os.symlink(os.getcwd() + '/' + src_dir, os.getcwd() + '/' + dst_dir)

# database
def set_value(id, key, val):
    tweets.update_one({'_id': id}, {'$set': {key: val}}, True)

def has_id(id):
    return bool(tweets.find({'_id': id}).count())

def get_tweets(key=None, value=None, sort=None):
    # init
    if not sort:
        sort = '_id'
    if not key and not value:
        return tweets.find().sort(sort)
    elif key and value:
        return tweets.find({key: value}).sort(sort)
    else:
        raise Error('Error: Give get_tweets key-value pair')

def print_tweet(t):
    if type(t) == dict:
        t = t['tweet']
    elif type(t) == tweepy.Status:
        t = t._json
    else:
        raise TypeError

    # Print tweet
    tweet_url = 'https://twitter.com/{name}/status/{id}'.format(
        name=t['user']['screen_name'],
        id=t['id'],
    )

    print('-' * 8)
    print(t['created_at'], '/ ♡ {} ↻ {} / {}'.format(
        t['favorite_count'],
        t['retweet_count'],
        tweet_url,
    ))
    print('{}(@{})'.format(t['user']['name'], t['user']['screen_name']))
    print(t['text'])

def update_date(daily=False, date=''):
    '''
    Update tweets statuses from new to old until api remaining become zero.

    param: daily - if True, append date tweets to the first of que.
    '''
    
    # initialize que file
    if not os.path.exists(setting['update_date_que']):
        with open(setting['update_date_que'], 'w') as f:
            yaml.dump(deque([]), f)

    # add daily tweets to the left of ques
    if daily:
        ques = deque([])
        for i in tweets.find({
                'meta.date': get_date(),
                'meta.removed': False,
                'meta.deny_collection': False,
        }).sort([('_id', -1)]):
            ques.appendleft(i['_id'])
    # add the date tweets to the left of ques
    elif date:
        ques = deque([])
        for i in tweets.find({
                'meta.date': date,
                'meta.removed': False,
                'meta.deny_collection': False,
        }).sort([('_id', -1)]):
            ques.appendleft(i['_id'])
    # load que file
    else:
        with open(setting['update_date_que']) as f:
            ques = yaml.load(f)
        
    # load tweets if there is no que
    if not ques:
        for i in tweets.find({
                'meta.removed': False,
                'meta.deny_collection': False,
        }).sort([('_id', -1)]):
            ques.append(i['_id'])
    
    # update tweets while api remaining
    api_remaining = get_show_status_remaining()
    fetch_count = api_remaining[0] - 5
    print('api remaining:', api_remaining[0])
    print('api reset time:', api_remaining[1])
    if fetch_count:
        for i in range(min(fetch_count, len(ques))):
            id = ques.popleft()
            tweet = tweets.find_one({'_id': id})
            retweet_and_record(id=id, retweet=False)
            print_tweet_summary(i, tweet)

        # save que
        with open(setting['update_date_que'], 'w') as f:
            yaml.dump(ques, f)

def print_tweet_summary(i, tweet):
    print('-' * 16)
    print('#{}'.format(i), tweet['meta']['date'], 'https://twitter.com/{}/statuses/{}'.format(tweet['tweet']['user']['screen_name'], tweet['_id']))
    print('{} (@{}) [{}/{}]'.format(tweet['tweet']['user']['name'], tweet['tweet']['user']['screen_name'], tweet['tweet']['favorite_count'], tweet['tweet']['retweet_count']))
    print(tweet['tweet']['text'])        
            
# api remainings
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

def save_themes_yaml():
    with open(setting['themes']) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes_yaml = yaml.load(f)
        print(themes_yaml)
    for theme in themes_yaml:
        themes.update_one({'date': theme['date']}, {'$set': theme}, True)

def write_themes_yaml():
    with open(setting['themes'], 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yaml.dump([i for i in themes.find().sort('date')], f, allow_unicode=True)
    
def update_themes():
    '''
    Get a new theme and togetter url from the official account's tweets, 
    and count tweets of the date in the database.
    '''
    ts = api.user_timeline(screen_name=setting['account'], count=100, tweet_mode='extended')
    ts = map(assign_text_to_full_text, reversed(ts))

    # update theme and togetter
    for t in ts:
        date = get_date(parse(t._json['created_at']).astimezone())
        print_tweet(t)

        # replace newline with space for theme matching
        t.text = t.text.replace('\n', ' ')

        # insert new theme of the day
        if not themes.find({'date': date}).count():
            match = re.findall(setting['theme_regex'], t.text)
            print('Date:', date)
            print('Found a new theme:', match)

            if match:
                theme = {}
                theme_name = ' / '.join(match)
                theme['theme'] = theme_name

                # if there has already exists the same theme, copy theme_en and category
                same_theme = themes.find({'theme': theme_name}).sort([('meta.date', -1)])

                # copy theme
                if same_theme.count():
                    same_theme = same_theme[0]
                    theme['category'] = same_theme['category']
                    theme['theme_en'] = same_theme['theme_en']

                # otherwise, initialize
                else:
                    theme['category'] = ['uncategorized']
                    theme['theme_en'] = ''

                # for request theme
                match = re.search(r'\(.*リクエスト.*\)', t.text)
                if match:
                    theme['category'].append('request')
                    theme['theme'] = re.sub('\(.*リクエスト.*\)', '', theme['theme'])

                # for season theme
                match = re.search(r'\(.*季節.*\)', t.text)
                if match:
                    theme['category'] = ['season']
                    theme['theme'] = re.sub('\(.*季節.*\)', '', theme['theme'])

                # for cloth theme
                match = re.search(r'\(.*衣装.*\)', t.text)
                if match:
                    theme['category'] = ['clothes']
                    theme['theme'] = re.sub('\(.*衣装.*\)', '', theme['theme'])
                    
                # for episode theme
                match = re.search(r'\(.*エピソード.*\)', t.text)
                if match:
                    theme['category'] = ['episode']
                    theme['theme'] = re.sub('\(.*エピソード.*\)', '', theme['theme'])
                    
                # for episode theme
                match = re.search(r'\(.*アンケート.*\)', t.text)
                if match:
                    theme['category'] = ['questionnaire']
                    theme['theme'] = re.sub('\(.*アンケート.*\)', '', theme['theme'])
                    
                # update database
                themes.update_one({'date': date}, {'$set': theme}, True)

                # retweet a official theme tweet
                #t.retweet()

        # update togetter url
        if setting['togetter']:
            non_togetter_tweets = themes.find({'date': date, 'togetter': {'$exists': False}})
            if non_togetter_tweets.count():
                if t.entities['urls'] and 'togetter.com/li/' in t.entities['urls'][0]['expanded_url']:
                    togetter = t.entities['urls'][0]['expanded_url']
                    themes.update_one({'date': date}, {'$set': {'togetter': togetter}}, True)
            
    # count event number and work number
    for num, theme in enumerate(themes.find().sort('date')):
        work_num = tweets.find({
            'meta.date': theme['date'],
            'meta.removed': False,
            'meta.deny_collection': False
        }).count()

        # Reset count for @precure_1draw_2
        if args.genre == 'precure' and theme['date'] and \
           theme['date'] >= parse('2017/1/14'):
            num -= 1000
        
        themes.update_one({'date': theme['date']},
                          {'$set': {'num': num, 'work_num': work_num}},
                          upsert=True)

    # count user number
    for i, date in enumerate(reversed(themes.distinct('date'))):
        if i > 20:
            break
        if not date:
            themes.update_one({'date': date}, {'$set': {'user_num': 0}})
        else:
            user_num = len(tweets.find({
                'meta.date': {'$lte': date},
                'meta.deny_collection': False,
                'meta.removed': False
            }).distinct('tweet.user.id'))
            themes.update_one({'date': date}, {'$set': {'user_num': user_num}}, True)

    write_themes_yaml()

def update_users():
    user_screen_names = tweets.find({
        'meta.deny_collection': False,
        'meta.removed': False,
        'tweet.user.screen_name': {
            '$not': re.compile(r'^{}$'.format(setting['account'][0])),
        },
    }).distinct('tweet.user.screen_name')
    users.delete_many({})
    for user_screen_name in user_screen_names:
        # get the latest tweet
        tweet = tweets.find(
            {'tweet.user.screen_name': user_screen_name},
            {'_id': {'$slice': -1}}
        )[0]
        num = tweets.find({'tweet.user.screen_name': user_screen_name, 'meta.removed': False}).count()
        cls = num // 10 * 10
        users.update_one(
            {'id': user_screen_name },
            {'$set': {
                'screen_name': user_screen_name,
                'num': num,
                'class': cls,
                'user': tweet['tweet']['user']}
            },
            upsert=True,
        )

def update_infos():
    with open(setting['info']) as f:
        infos_yaml = yaml.load(f)
    for id, info in enumerate(reversed(infos_yaml)):
        info_dict = {}
        info_dict['id'] = id
        for k, v in info.items():
            info_dict[k] = v
        print(info_dict)
        infos.update_one({'id': id}, info_dict, True)

def get_user_work_number(id):
    '''Return the number of the id tweet work of the user.'''
    screen_name = get_tweets('_id', id)[0]['tweet']['user']['screen_name']
    tweets = get_tweets('tweet.user.screen_name', screen_name)
    for num, tweet in enumerate(tweets):
        if tweet['_id'] == id:
            return num + 1

def update_labels(id, force=False):
    '''Update labels of the database which is used at each tweet's header.'''
    tweet = get_tweets('_id', id)[0]
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
    screen_names = tweets.distinct('tweet.user.screen_name')
    lucky_nums = list(range(10, 1001, 10))

    for sn in screen_names:
        print('-' * 16)
        print('Update labels of user:', sn)
        user_tweets = tweets.find({'tweet.user.screen_name': sn, 'meta.removed': False}).sort('_id')
        
        for num, tweet in enumerate(user_tweets, 1):
            labels = []
            print_tweet_summary(num, tweet)

            # Add lucky number
            if num == 1:
                labels.append('初参加')
            else:
                if num in lucky_nums:
                    labels.append(str(num))
           
            # Add gif label
            if not 'imgs' in tweet['meta']:
                retweet_and_record(id=tweet['_id'], retweet=False)
                print('not imgs')
            imgs = tweet['meta']['imgs']
            if imgs and '/tweet_video_thumb/' in str(imgs[0]['img_url']): # str() for bool value
                print(tweet)
                labels.append('GIF')
           
            if not labels:
                labels = ['none']
                
            print(tweet['_id'], 'Set labels:', labels)
            set_value(tweet['_id'], 'meta.labels', labels)
        
def make_chart():
    def col_list(key):
        return [i[key] for i in themes.find().sort('num') if i['date']]

    days = col_list('num')
    nums = col_list('work_num')
    user_nums = col_list('user_num')
     
    # ax1: works num, ax2: user num
    fig, ax = plt.subplots()

    ax1 = plt.axes()
    ax2 = ax1.twinx()
     
    ax1.plot(days, user_nums, '-', color='lightsteelblue', linewidth=1)
    ax2.plot(days, nums, '-', color='palevioletred', linewidth=1)

    fig.autofmt_xdate()

    # set limit
    ax1.set_xlim(0, max(days) + 10)
    ax1.set_ylim(0, max(user_nums) + 30)
    ax2.set_ylim(0, max(nums) + 15)

    # set locator
    ax1.xaxis.set_major_locator(plt.MultipleLocator(200))
    ax1.yaxis.set_major_locator(plt.MultipleLocator(200))
    ax2.xaxis.set_major_locator(plt.MultipleLocator(100))
    ax2.yaxis.set_major_locator(plt.MultipleLocator(25))

    # set grid
    ax2.grid(True)

    # label
    fp = FontProperties(fname='Hiragino Sans GB W3.otf')
    ax1.set_xlabel('回数', fontproperties=fp)
    ax1.set_ylabel('累計参加者数', fontproperties=fp)
    ax2.set_ylabel('作品数/回', fontproperties=fp)
     
    # legend
    p1 = plt.Rectangle((0, 0), 1, 1, fc="lightsteelblue", ec='lightsteelblue')
    p2 = plt.Rectangle((0, 0), 1, 1, fc="palevioletred", ec='palevioletred')
    ax1.legend([p1, p2], ['累計参加者数', '作品数'], loc='upper left', prop=fp, )

     
    #plt.title('作品数の変化', fontproperties=fp)
    plt.savefig(setting['static_dirs'] + 'chart.svg')

    # en
    ax1.set_xlabel('#', fontproperties=fp)
    ax1.set_ylabel('Total perticipants')
    ax2.set_ylabel('Works')
    ax1.legend([p1, p2], ['Total perticipants', 'Works'], loc='upper left')
    plt.savefig(setting['static_dirs'] + 'chart-en.svg')

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
            if not os.path.exists(save_dir):
                os.mkdir(save_dir)
            filename = str(theme['date'].date()) + '.svg'
            plt.savefig(save_dir +  '/' + filename)
            plt.close()
         
            total = len(favs[theme['date']])
            rank = sorted(favs[theme['date']], reverse=True).index(user_fav) + 1
            percent = int((rank / total) * 100)
         
            text = 'Fav+RT: {}<br>Rank: {} / {} ({}%)'.format(user_fav, rank, total, percent)     

def fav_plus_rt(tweet):
    fav = tweet['tweet']['favorite_count']
    rt = tweet['tweet']['retweet_count']
    if fav + rt > 150:
        return 150
    else:
        return fav + rt

def show_status(id):
    if has_id(id):
        print_tweet(tweets.find_one(id)['tweet'])
    else:
        t = api.get_status(id=id, tweet_mode='extended')
        t = assign_text_to_full_text(t)
        print_tweet(t)

def init(_genre):
    # load setting file
    global genre
    global setting
    global ignores
    global api
    global vision
    global tweets
    global themes
    global users
    global infos
    
    genre = _genre
    with open('settings.yaml') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        setting = yaml.load(f)[genre]
    
    with open(setting['ignores']) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        ignores = yaml.load(f)

    # prepare twitter object
    api = get_api(setting['rt_account'])

    #  prepare Google Cloud Vision API
    with open('.google-api-key') as f:
        key = f.read().strip()
    vision = build('vision', 'v1', developerKey=key)
    
    tweets = get_mongo_client()[genre + '_1draw_collections']['tweets']
    themes = get_mongo_client()[genre + '_1draw_collections']['themes']
    users = get_mongo_client()[genre + '_1draw_collections']['users']
    infos = get_mongo_client()[genre + '_1draw_collections']['infos']

# Define global variable
genre = None
setting = None
ignores = None
api = None
vision = None
tweets = None
themes = None
users = None
infos = None

if __name__ == '__main__':
    command_choices = [
        'update_themes',
        'save_themes_yaml',
        'save_tweet',
        'update_users',
        'make_chart',
        'generate_rank_html',
        'check_new_ignore_user_list',
        'update_labels_all',
    ]
    parser = argparse.ArgumentParser()
    parser.add_argument('genre')
    parser.add_argument('command', choices=command_choices)
    parser.add_argument('--ids', nargs='+')
    parser.add_argument('--screen_names', nargs='+')
    args = parser.parse_args()

    init(args.genre)
    
    if args.command == 'update_themes':
        update_themes()
    elif args.command == 'save_themes_yaml':
        save_themes_yaml()
    elif args.command == 'save_tweet':
        if args.ids:
            ids = [id.split('/')[-1] for id in args.ids]
            save_tweet(ids=ids)
        elif args.screen_names:
            save_tweet(screen_names=args.screen_names)
        else:
            save_tweet()
    elif args.command == 'update_users':
        update_users()
    elif args.command == 'update_labels_all':
        update_labels_all()
    elif args.command == 'make_chart':
        make_chart()
    elif args.command == 'generate_rank_html':
        generate_rank_html()
    elif args.command == 'check_new_ignore_user_list':
        check_new_ignore_user_list()
    
else:
    init('precure')    

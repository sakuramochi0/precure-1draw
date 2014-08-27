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
import sqlite3
from os import path
from io import BytesIO
import subprocess
from pprint import pprint
import urllib

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
    with open('.credentials') as f:
        app_key, app_secret, oauth_token, oauth_secret = [x.strip() for x in f]
    t = Twython(app_key, app_secret, oauth_token, oauth_secret)
    return t

def stream_auth():
    '''Authenticate the account and return the twitter stream instance.'''
    # read app credentials
    with open('.credentials') as f:
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
    stream.statuses.filter(track='#' + hash_tags[0] + ' ' + triger)

def auto_retweet_rest(past=3, retweet=True):
    '''Retweet all the tweet which have the hash_tag by rest.'''
    # gather
    max_id=''
    tweets = []
    for i in range(past):
        res = t.search(q='#' + hash_tags[0] + ' -RT', count=100, result_type='recent', max_id=max_id)
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
                        set_col(id, 'removed', 'deleted')
                        print('404 Not found and marked "deleted":', id)
                        print_tweet(id)
                    else:
                        print('404 Not found and not in database:', id)
                elif e.error_code == 403:
                    if has_id(id):
                        set_col(id, 'removed','locked')
                        print('403 Tweet has been locked and marked "locked":', id)
                        print_tweet(id)
                    else:
                        print('403 Tweet has been locked and not in database:', id)
                elif e.error_code == 429: # API remaining = 0
                    print('api not remaining')
                    return get_id_tweet(id)
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
            set_col(id, 'tweet', tweet) # update
        tweet = get_id_tweet(id)

    # excluding filters
    if tweet_filter(tweet, new=new) or exception:
        
        with open(ignores_file) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            ignores = yaml.load(f)

        # get date
        if not 'date' in tweet.keys():
            date = get_date(tweet['tweet']['created_at'])
        else:
            date = tweet['date']

        # exclude a tweet of deny_retweet and set it
        if not 'retweeted' in tweet:
            retweeted = False
        else:
            retweeted = tweet['retweeted']
        if (tweet['tweet']['user']['screen_name'] in ignores['deny_retweet_user']) or (tweet['tweet']['user']['id'] in ignores['deny_retweet_user']):
            deny_retweet = True
        else:
            deny_retweet = False
            if retweet and not retweeted:
                try:
                    res = t.retweet(id=tweet['tweet']['id'])
                    if res['retweeted']:
                        retweeted = True
                except TwythonError as e:
                    if e.error_code == 403:
                        print('Double retweet:', tweet['tweet']['id'])
                        retweeted = True

        # set deny_collection
        if (tweet['tweet']['user']['screen_name'] in ignores['deny_collection_user']) or (tweet['tweet']['user']['id'] in ignores['deny_collection_user']):
            deny_collection = True
        else:
            deny_collection = False

        # set exception
        if exception or (not new and tweet['exception']):
            exception = True
            #print(tweet['tweet']['id'], 'Accepted by exception')
        else:
            exception = False
            
        # update database record
        upsert_tweet(tweet['tweet']['id'], tweet['tweet'], date, deny_retweet, deny_collection, exception, retweeted)

        # get images
        if 'imgs' not in tweet.keys():
            store_image(tweet['tweet']['id'])

        # add labels
        update_labels(tweet['tweet']['id'])

        return tweet
        
def including_hash_tag(tweet):
    # 1. if any similar hash_tags in tweet['entities']['hashtags']
    if 'hashtags' in tweet['tweet']['entities']: # tweet has hashtags data
        tweet_tags = tweet['tweet']['entities']['hashtags']
        for tweet_tag in tweet_tags:
            if difflib.get_close_matches(tweet_tag['text'], hash_tags):
                return True
    # 2. or if any similar hash_tags in tweet['text']
    for match in re.finditer('プリキュア', tweet['tweet']['text']):
        tweet_tag = tweet['tweet']['text'][match.start():match.start()+22]
        if difflib.get_close_matches(tweet_tag, hash_tags):
            return True

    # otherwise, not including any hash_tag
    return False

def tweet_filter(tweet, new=False):
    '''Filter a spam tweet. If the tweet is spam, return False, or return True.'''
    with open(ignores_file) as f:
        ignores = yaml.load(f)

    # allow exception
    if not new:
        if tweet['exception']:
            return True

    # if ignore_user
    hit = ''
    if (tweet['tweet']['user']['screen_name'] in ignores['ignore_user']) or (tweet['tweet']['user']['id'] in ignores['ignore_user']):
        hit = 'Hit ignore_user:'
        return False
    # if ignore_id tweet
    elif tweet['tweet']['id'] in ignores['ignore_id']:
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
    elif triger not in tweet['tweet']['text']:
        hit = 'Not including triger:'
    # if deleted
    elif not new and tweet['removed'] == 'deleted':
        hit = 'Already deleted:'
    else:
        # if including ignore_word
        for word in ignores['ignore_word']:
            if re.search(word, tweet['tweet']['text']): 
                hit += 'Hit ignore_word "{}":'.format(word)
    if hit:
        # print('-' * 16)
        # print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
        # print(hit)
        # print_tweet(None, tweet=tweet)
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
    tweet = get_id_tweet(id)
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
            soup = BeautifulSoup(requests.get(url + '/full').text)
            img_url = soup('div', id='media-full')[0].img['src']
        elif 'photozou.jp' in url:
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup(itemprop='image')[0]['src']
        elif 'p.twipple.jp' in url:
            img_url = url.replace('p.twipple.jp/', 'p.twpl.jp/show/orig/')
        elif 'yfrog.com' in url:
            url = url.replace('yfrog.com', 'twitter.yfrog.com')
            r = requests.get(url)
            soup = BeautifulSoup(r.text)
            url = url + soup(id='continue-link')[0].a['href']
            r = requests.get(url)
            soup = BeautifulSoup(r.text)
            img_url = soup(id='main_image')[0]['src']
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
            save_dir = img_dir + tweet['tweet']['user']['id_str'] + '/'
            if not path.exists(save_dir):
                os.mkdir(save_dir)
            with open(save_dir + filename, 'wb') as f2:
                f2.write(img)
                print('Downloaded: {} -> {} -> {}'.format(url, img_url, save_dir + filename))
        else:
            filename = False
            print('No image exists.')

        imgs.append({'url': url, 'img_url': img_url, 'filename': filename})

    # set imgs after save all the imgs loop
    set_col(id, 'imgs', imgs)

def make_symlinks_to_img_dir():
    tweets = get_tweets()
    for tweet in tweets:
        src_dir = img_dir + '-' + tweet['tweet']['user']['id_str']
        dst_dir = img_dir + '-' + tweet['tweet']['user']['screen_name']
        if not path.islink(dst_dir):
            os.symlink(os.getcwd() + '/' + src_dir, os.getcwd() + '/' + dst_dir)

# database
def db_con():
    '''Init the tweets database.'''
    con = sqlite3.connect('tweets.sqlite', detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    sqlite3.register_adapter(dict, lambda x: json.dumps(x, ensure_ascii=False))
    sqlite3.register_converter('dict', lambda x: json.loads(x.decode('utf-8')))
    sqlite3.register_adapter(list, lambda x: json.dumps(x, ensure_ascii=False))
    sqlite3.register_converter('list', lambda x: json.loads(x.decode('utf-8')))
    return con

def db_init():
    con = db_con()
    con.execute('create table tweets (id int primary key not null,\
                                      tweet dict not null,\
                                      date text not null,\
                                      deny_retweet int,\
                                      deny_collection int,\
                                      removed text,\
                                      imgs list not null)')

def set_col(id, col, val):
    con = db_con()
    with con:
        con.execute('update tweets set {}=? where id=?'.format(col), (val, id))

def has_id(id):
    con = db_con()
    with con:
        return len(con.execute('select * from tweets where id=?', (id, )).fetchall()) == 1

def upsert_tweet(id, tweet, date, deny_retweet, deny_collection, exception, retweeted):
    con = db_con()
    try:
        with con:
            con.execute('insert into tweets(id, tweet, date, deny_retweet, deny_collection, exception, retweeted) values (?,?,?,?,?,?,?)', (id, tweet, date, deny_retweet, deny_collection, exception, retweeted))
            print('-' * 16)
            print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
            print('Add a new record: {} deny_retweet: {}, deny_collection: {}'.format(id, deny_retweet, deny_collection))
    except:
        try:
            with con:
                con.execute('update tweets set tweet=?, date=?, deny_retweet=?, deny_collection=?, exception=?, retweeted=? where id=?', (tweet, date, deny_retweet, deny_collection, exception, retweeted, id))
        except sqlite3.Error as e:
            print(e)
            time.sleep(5)

def get_id_tweet(id):
    con = db_con()
    return con.execute("select * from tweets where id=?", (id, )).fetchone()

def destroy_id_tweet(id):
    con = db_con()
    tweet = get_id_tweet(id)
    with con:
        con.execute('delete from tweets where id=?', (id, ))
    print('Permanent delete tweet:')
    pprint(tweet['tweet'])

def get_tweets(date='', screen_name=''):
    con = db_con()
    if date:
        ts = [t for t in con.execute('select * from tweets where date=? order by id', (date, ))]
    elif screen_name:
        for tweet in con.execute('select * from tweets order by id'):
            if tweet['tweet']['user']['screen_name'] == screen_name:
                user_id = tweet['tweet']['user']['id']
                ts = [t for t in con.execute('select * from tweets order by id') if t['tweet']['user']['id'] == user_id]
                break
    else:
        ts = [t for t in con.execute('select * from tweets order by id')]

    if not ts:
        # print('There is no tweets in the database.')
        return None
    else:
        return ts

def print_tweet(id=0, tweet=None):
    if id:
        tweet = get_id_tweet(id)
    print(tweet['tweet']['id']) # not tweet['id'] because tweet can have only 'tweet' key
    print('https://twitter.com/{}/status/{}'.format(tweet['tweet']['user']['screen_name'], tweet['tweet']['id']))
    #print('{} (@{})'.format(tweet['tweet']['user']['name'], tweet['tweet']['user']['screen_name']))
    #print(tweet['tweet']['text'])
    #pprint(tweet['tweet'])

def print_all_tweets():
    ts = get_tweets()
    for i in ts:
        print('{} {} {}/{}/{} {}({}) | {}'.format(i['id'], i['date'], i['removed'], i['deny_collection'], i['deny_retweet'], i['tweet']['user']['name'], i['tweet']['user']['screen_name'], i['tweet']['text'][:10]))

def store_image_all():
    tweets = get_tweets()
    for i, tweet in enumerate(tweets):
        print('-' * 16)
        print('#', i, tweet['id'])
        if tweet['removed'] == '0':
            try:
                store_image(tweet['id'])
            except:
                pass
            time.sleep(1)

def store_image_date(date=''):
    if not date:
        date = get_date()
    tweets = get_tweets(date=date)
    for i, tweet in enumerate(tweets):
        print('-' * 16)
        print('#', i, tweet['id'])
        if tweet['removed'] == '0':
            try:
                store_image(tweet['id'])
            except:
                pass
            time.sleep(1)

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

def update_themes():
    '''Get a new theme from the official account's tweets.'''
    with open(themes_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        themes = yaml.load(f)
        tweets = get_tweets()

        res = t.get_user_timeline(screen_name='precure_1draw', count=100)
        for tweet in res:
            date = get_date(tweet['created_at'])
            if date not in themes:
                match = re.findall('(?:“|”|\'|")(.+?)(?:“|”|\'|")', tweet['text'])
                if match:
                    themes[date] = {}
                    themes[date]['theme'] = ' / '.join(match)
                    themes[date]['theme_en'] = ''
                    themes[date]['num'] = 0
                    t.retweet(id=tweet['id'])
        for date in themes:
            togetter_url = [tweet['tweet']['entities']['urls'][0]['expanded_url']
                            for tweet in tweets
                            if tweet['tweet']['entities']['urls']
                            and 'togetter.com'
                            in tweet['tweet']['entities']['urls'][0]['expanded_url']
                            and tweet['date'] == date]
            if togetter_url:
                themes[date]['togetter'] = togetter_url[0]
            else:
                themes[date]['togetter'] = ''
        f.seek(0)
        f.truncate()
        yaml.dump(themes, f, allow_unicode=True)

    # for use of admin page list
    with open(html_dir + 'date/' + themes_file, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(themes, f, ensure_ascii=False)

    update_user_nums()

def update_user_nums():
    with open(themes_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        themes = yaml.load(f)

        users = []
        for date in sorted(themes):
            if date == '0-misc':
                themes[date]['user_num'] = 0
            else:
                tweets = get_tweets(date)
                if tweets:
                    users.extend([t['tweet']['user']['id'] for t in tweets if tweet_filter(t)])
                    themes[date]['user_num'] = len(set(users))
                else:
                    themes[date]['user_num'] = len(set(users))
        f.seek(0)
        f.truncate()
        yaml.dump(themes, f, allow_unicode=True)
        
def print_first_participants():
    with open(themes_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        themes = yaml.load(f)

        users = []
        for date in sorted(themes):
            if date != '0-misc':
                print('-'*8)
                print(date)
                tweets = get_tweets(date)
                old = set(users)
                users.extend([t['tweet']['user']['id'] for t in tweets])
                new = set(users) - old
                print(new)
                for text in [tweet['tweet']['text'] for tweet in tweets if tweet['tweet']['user']['id'] in new]:
                    print('*', text)
                # print(set(users))
                print(len(new))
                
def last_update(lang='ja'):
    '''Return datetime.now() as formated text.'''
    if lang == 'ja':
        return datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')
    elif lang == 'en':
        return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
def print_user_work_number(screen_name):
    '''Print the work's number and text of the user.'''
    tweets = get_tweets(screen_name=screen_name)
    for num, tweet in enumerate(tweets):
        print(num+1, tweet['tweet']['text'])
        pprint(tweet['removed'])

def get_user_work_number(id):
    '''Return the number of the id tweet work of the user.'''
    screen_name = get_id_tweet(id)['tweet']['user']['screen_name']
    tweets = get_tweets(screen_name=screen_name)
    for num, tweet in enumerate(tweets):
        if tweet['id'] == id:
            return num + 1

def update_labels(id, force=False):
    '''Update labels of the database which is used at each tweet's header.'''
    tweet = get_id_tweet(id)
    lucky_nums = list(range(10, 1001, 10))
    labels = []

    if tweet['labels'] and not force:
        return
    
    # lucky number
    num = get_user_work_number(id)
    print(num)
    if num == 1:
        labels.append('初参加')
    else:
        for lucky_num in lucky_nums:
            if num == lucky_num:
                labels.append(str(lucky_num))

    # gif
    print(id)
    if '/tweet_video_thumb/' in str(tweet['imgs'][0]['img_url']): # str() for bool value
        labels.append('GIF')

    if not labels:
        labels = ['none']
        
    print(id, 'Set labels:',labels)
    set_col(id, 'labels', labels)

def get_id_all():
    return [t['id'] for t in get_tweets()]

def update_labels_all():
    tweets = get_tweets()
    user_ids = set([tweet['tweet']['user']['id'] for tweet in tweets])
    lucky_nums = list(range(10, 1001, 10))

    for user_id in user_ids:
        print('-'*8)
        print('Update labels of user:', [tweet['tweet']['user']['screen_name'] for tweet in tweets if tweet['tweet']['user']['id'] == user_id][0])
        user_tweets = [tweet for tweet in tweets if tweet['tweet']['user']['id'] == user_id]
        
        for num, tweet in enumerate(user_tweets):
            labels = []
            num += 1
            print(num, tweet['tweet']['text'])

            # lucky number
            if num == 1:
                labels.append('初参加')
            else:
                if num in lucky_nums:
                    labels.append(str(num))
           
            # gif
            if '/tweet_video_thumb/' in str(tweet['imgs'][0]['img_url']): # str() for bool value
                labels.append('GIF')
           
            if not labels:
                labels = ['none']
                
            print(tweet['id'], 'Set labels:',labels)
            set_col(tweet['id'], 'labels', labels)
        
def get_labels_html(tweet, extra_class=''):
    labels = []
    for label in tweet['labels']:
        if label == 'none':
            break
        if label == 'GIF':
            title = 'アニメーションGIFの画像です。クリックして見てみましょう。'
            color = '#5CB85C' # green
        elif label == '初参加':
            title = '今回が初参加です！'
            color = '#D43F3A' # red
        elif label.isdigit():
            title = '今回で{}回目の参加です！'.format(label)
            color = '#FF7200' #orange
        else:
            title = 'その他'
            color = 'gray'
        labels.append('<a href="../labels.html"><span class="label {}" title="{}" style="text-align: left; background-color: {}">{}</span></a>'.format(extra_class, title, color, label))
    if extra_class:
        html = '{}'.format('\n'.join(labels))
    else:
        html = '<div class="labels" style="position: absolute;">\n{}\n</div>'.format('\n'.join(labels))
    return html

def chart():
    with open('themes.yaml') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        ts = yaml.load(f)
     
    days = [(parse(day) - datetime.datetime(2014, 4, 19)).days for day in sorted(ts) if day != '0-misc']
    nums = [ts[day]['num'] for day in sorted(ts) if day != '0-misc']
    user_nums = [ts[day]['user_num'] for day in sorted(ts) if day != '0-misc']
     
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

    #ax1.set_xticklabels(rotation=45)

    # set locator
    ax1.xaxis.set_major_locator(plt.MultipleLocator(5))
    ax1.yaxis.set_major_locator(plt.MultipleLocator(100))
    ax2.xaxis.set_major_locator(plt.MultipleLocator(5))
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
    plt.savefig('html/chart.svg')

    # en
    ax1.set_xlabel('#', fontproperties=fp)
    ax1.set_ylabel('Total perticipants')
    ax2.set_ylabel('Works')
    ax1.legend([p1, p2], ['Total perticipants', 'Works'], loc='upper left')
    plt.savefig('html/chart-en.svg')

def generate_index_html():
    '''Generate index.html of the 1draw-collection.'''
    chart()
    locale.setlocale(locale.LC_ALL, '')
    with open(index_html_template_file) as f:
        index_html_template = f.read()

    # infomartion board
    with open('info.yaml') as f:
        infos = yaml.load(f)
    soup = BeautifulSoup()
    info_table = soup.new_tag('table')
    for info in infos:
        tr = soup.new_tag('tr')
        # date
        td = soup.new_tag('td')
        td.append(BeautifulSoup(info[0]))
        tr.append(td)
        # ja
        td = soup.new_tag('td')
        td.append(BeautifulSoup(info[1]))
        td['class'] = 'ja'
        tr.append(td)
        # en
        td = soup.new_tag('td')
        td.append(BeautifulSoup(info[2]))
        td['class'] = 'en'
        tr.append(td)
        info_table.append(tr)

    # main
    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)
    for ribbon_name in ribbon_names:
        trs = []
        for num, (date, item) in enumerate(reversed(sorted(themes.items()))):
            num = len(themes) - num - 1

            if date == '0-misc':
                date_str = '-'
            else:
                date_str = parse(date).strftime('<span class="year">%Y年</span>%m月%d日(%a)')
                date_str_en = parse(date).strftime('<span class="year">%Y/</span>%m/%d')

            if path.exists(html_dir + 'date/' + ribbon_name + date + '.html'):
                link = '<a href="date/{ribbon_name}{date}.html">{theme}</a>'.format(ribbon_name=ribbon_name, date=date, theme=item['theme'])
                if item['theme_en']:
                    link_en = '<a href="date/{ribbon_name}{date}.html">{theme_en}</a>'.format(ribbon_name=ribbon_name, date=date, theme_en=item['theme_en'])
                else:
                    link_en = '<a href="date/{ribbon_name}{date}.html">{theme}</a>'.format(ribbon_name=ribbon_name, date=date, theme=item['theme'])
            else:
                link = item['theme']
                link_en = item['theme_en']
                if not link_en:
                    link_en = item['theme']

            if item['num'] == 0:
                work_num = '-'
            else:
                work_num = int(item['num'])

            if item['togetter']:
                togetter = '<a href="{}"><i class="fa fa-square fa-lg" style="color: #7fc6bc" title="Togetter のまとめを見る"></i></a>'.format(item['togetter'])
            else:
                togetter = ''

            tr = '''<tr>
            <td class="num">#{num:2d}</td>
            <td class="date ja">{date_str}</td>
            <td class="date en">{date_str_en}</td>
            <td class="theme ja">{link}</td>
            <td class="theme en">{link_en}</td>
            <td class="work_num">{work_num}</td>
            <td class="togetter">
              {togetter}
            </td>
            </tr>'''.format(num=num, date_str=date_str, date_str_en=date_str_en, link=link, link_en=link_en, work_num=work_num, togetter=togetter)
            trs.append(tr)
        html = index_html_template.format(info_table=info_table,
                                          ribbon_name=ribbon_name[:-1],
                                          list=''.join(trs),
                                          last_update=last_update(),
                                          last_update_en=last_update(lang='en'))
        with open(html_dir + ribbon_name + 'index.html', 'w') as f:
            f.write(html)

def generate_date_html(date='', fetch=True):
    '''Generate the specific date page of the 1draw-collection.'''
    if not date:
        date = get_date()

    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)
    if date not in themes:
        # print('There is no tweet of the day.')
        return
    theme = themes[date]['theme']
    theme_en = themes[date]['theme_en']
    if not theme_en:
        theme_en = themes[date]['theme']

    with open(date_html_template_file) as g:
        date_html_template = g.read()
    with open(tweet_html_template_file) as g:
        tweet_html_template = g.read()
    with open(tweet_admin_html_template_file) as g:
        tweet_admin_html_template = g.read()

    # generate html
    date_tweets = get_tweets(date)
    tweets = []

    if not date_tweets:
        return
    for tweet in date_tweets:
        if (not tweet['deny_collection']) and (tweet['removed'] == '0') and (not tweet['tweet']['user']['screen_name'] == 'precure_1draw'): # condition to collection
            tweets.append(tweet)
    if not tweets:
        print('There is no tweet of the day.')
        return

    if date == '0-misc': # if misc, new to old order
        tweets = reversed(tweets)
    
    tweet_htmls = {}
    if fetch:
        api_remaining, api_reset = get_show_status_remaining()
    count = 0
    for tweet in tweets:
        count += 1
        if fetch and count >= api_remaining:
            sleep_until_api_reset()
            count = 0
            api_remaining, api_reset = get_show_status_remaining()

        tweet = retweet_and_record(id=tweet['id'], retweet=False, fetch=fetch)
        if not tweet: # if the tweet is deleted, locked, or something
            continue

        # remove tag
        linked_text = re.sub('\n?\s*#プリキュア版深夜の真剣お絵描き60分一本勝負\s*\n?', ' ', tweet['tweet']['text'])

        # replace t.co to display_url and linkify
        if 'media' in tweet['tweet']['entities']: # tweet has official image
            key = 'media'
        elif 'urls' in tweet['tweet']['entities']:
            key = 'urls'
        else:
            continue
        for urls in tweet['tweet']['entities'][key]:
            linked_text = linked_text.replace(urls['url'], '<a href="{}">{}</a>'.format(urls['expanded_url'], urls['display_url']))

        # add labels
        labels = get_labels_html(tweet)
        
        # add imgs
        imgs = []
        try:
            for img in tweet['imgs']:
                if img['filename']:
                    img_src = '../' + img_dir + tweet['tweet']['user']['id_str'] + '/' + img['filename']
                    img_style = ''
                else: # no image
                    img_src = ''
                    img_style='display: none;'
                imgs.append('<img class="illust" src="{img_src}" title="ツイートを見る" style="{img_style}">'.format(img_src=img_src, img_style=img_style))
            imgs = '\n\n'.join(imgs)
        except:
            print_tweet(tweet=tweet)

        time = parse(tweet['tweet']['created_at'])
        for ribbon_name in ribbon_names:
            if ribbon_name == 'admin-':
                tweet_admin = tweet_admin_html_template.format(id=tweet['id'],
                                                               user_id=tweet['tweet']['user']['id'])
            else:
                tweet_admin = ''

            tweet_html = tweet_html_template\
              .format(id=tweet['id'],
                      name=tweet['tweet']['user']['name'],
                      screen_name=tweet['tweet']['user']['screen_name'],
                      url=tweet['imgs'][0]['url'],
                      img_url=tweet['imgs'][0]['img_url'],
                      labels=labels,
                      imgs=imgs,
                      img_style=img_style,
                      icon_src=tweet['tweet']['user']['profile_image_url_https'],
                      icon_src_bigger=tweet['tweet']['user']['profile_image_url_https'].replace('_normal.', '_bigger.'),
                      text=linked_text,
                      time_iso=time.isoformat(),
                      time_utc=time.strftime('%Y年%m月%d日 %H:%M:%S (%Z)'),
                      time_jtc=time.astimezone(pytz.timezone('Asia/Tokyo')).strftime('%Y年%m月%d日 %I:%M %p'),
                      retweet_count=tweet['tweet']['retweet_count'],
                      favorite_count=tweet['tweet']['favorite_count'],
                      tweet_admin=tweet_admin)
            if ribbon_name not in tweet_htmls:
                tweet_htmls[ribbon_name] = []
            tweet_htmls[ribbon_name].append(tweet_html)

    # update theme num
    with open(themes_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        themes = yaml.load(f)
        themes[date]['num'] = len(tweet_htmls[''])
        f.seek(0)
        f.truncate()
        yaml.dump(themes, f, allow_unicode=True)

    if date == '0-misc':
        date_str = ''
        num = ''
        h2 = '{theme}のまとめ'.format(theme=theme)
        h2_en = 'Collections of {theme_en}'.format(theme_en=theme_en)
    else:
        date_str = parse(date).strftime('%Y年%m月%d日')
        date_str_en = parse(date).strftime('<span class="year">%Y/</span>%m/%d')
        num = '第{}回'.format(sorted(themes).index(date))
        h2 = '{date_str}のまとめ<br />テーマ: {theme}'.format(date_str=date_str, theme=theme)
        h2_en = 'Collections on {date_str_en}<br />Theme: {theme_en}'.format(date_str_en=date_str_en, theme_en=theme_en)
    for ribbon_name in ribbon_names:
        tweets_html = '\n\n'.join(tweet_htmls[ribbon_name])
        html = date_html_template.format(ribbon_name=ribbon_name[:-1],
                                         h2=h2,
                                         h2_en=h2_en,
                                         num=num,
                                         date=date,
                                         date_str=date_str,
                                         theme=theme,
                                         theme_en=theme_en,
                                         theme_tweet=urllib.parse.quote(theme),
                                         tweets=tweets_html,
                                         last_update=last_update())
                                         
        with open(html_dir + 'date/' + ribbon_name + date + '.html', 'w') as f:
            f.write(html)

def generate_date_html_circulate():
    '''Generate the date page of the 1draw-collection in order.'''
    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)
    with open(date_que_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ques = yaml.load(f)

        if not ques:
            ques = sorted(list(themes.keys())) # keys ordered new -> old
        date = ques.pop()

        print('Updating:', date)
        generate_date_html(date=date)

        f.seek(0)
        f.truncate()
        yaml.dump(ques, f)

def generate_date_html_all():
    '''Generate all the date pages of the 1draw-collection.'''
    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)

    for date in reversed(sorted(themes)):
        print('Updating:', date)
        generate_date_html(date=date, fetch=False)

def generate_user_html_all():
    '''Generate all the user gallery pages.'''
    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)
    with open(user_html_template_file) as f:
        template = f.read()
    with open(ignores_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        ignores = yaml.load(f)
    tweets = get_tweets()
    
    # select all the condidates
    users = set([tweet['tweet']['user']['screen_name'] for tweet in tweets
                if tweet['tweet']['user']['screen_name'] not in ignores['deny_collection_user']
                and tweet['tweet']['user']['id'] not in ignores['deny_collection_user']
                and tweet['tweet']['user']['screen_name'] not in ignores['deny_collection_gallery_user']
                and tweet['tweet']['user']['id'] not in ignores['deny_collection_gallery_user']
                ])
    
    os.chdir(html_dir + 'user/')
    for screen_name in users:
        # -1 means getting item from the latest tweet
        user_id = [tweet for tweet in tweets if tweet['tweet']['user']['screen_name'] == screen_name][-1]['tweet']['user']['id']
        user_tweets = [tweet for tweet in tweets if (tweet['tweet']['user']['id'] == user_id) and (tweet['removed'] == '0')]
        if not user_tweets:
            continue
        name = user_tweets[-1]['tweet']['user']['name']
        imgs = []
        for tweet in reversed(user_tweets):
            for img in tweet['imgs']:
                if img['filename']:
                    src = '../' + img_dir + tweet['tweet']['user']['id_str'] + '/' + img['filename']
                    labels = get_labels_html(tweet, extra_class='user-label')
                    date = tweet['date'] if tweet['date'] != '0-misc' else ''
                    try:
                        caption = '{labels}{date}<br><span class="ja">{theme}</span><span class="en">{theme_en}</span>'.format(labels=labels, date=date, theme=themes[tweet['date']]['theme'], theme_en=themes[tweet['date']]['theme_en'])
                    except:
                        pprint(tweet['tweet'])
                    link = 'https://twitter.com/{}/status/{}'.format(tweet['tweet']['user']['screen_name'] ,tweet['id'])
                    imgs.append('<a href={link}><figure><img class="gallery" src="{src}"><figcaption>{caption}</figcaption></figure></a>'.format(link=link, src=src, caption=caption))
      
        html = template.format(name=name, screen_name=screen_name, imgs='\n\n'.join(imgs), last_update=last_update())
        with open(screen_name + '.html', 'w') as f:
            f.write(html)

def fav_plus_rt(tweet):
    return tweet['tweet']['favorite_count'] + tweet['tweet']['retweet_count']

def generate_rank_html():
    """
    Generate user rank pages.
    """
    with open('rank_users.yaml') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        screen_names = yaml.load(f)
    
    with open('themes.yaml') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)
     
    tweets = get_tweets()
    for screen_name in screen_names:
        frs = {}
        imgs = []
        for date in reversed(sorted(themes)):
            frs[date] = [fav_plus_rt(tweet) for tweet in tweets
                         if tweet['date'] == date and tweet['tweet']['favorite_count'] < 150]
         
            tweet = [tweet for tweet in tweets
                   if tweet['date'] == date and tweet['tweet']['user']['screen_name'] == screen_name]
            if tweet:
                tweet = tweet[0]
                fav = fav_plus_rt(tweet)
            else:
                continue
         
            fig, ax = plt.subplots()
            n, bins, patches = plt.hist(frs[date], color='skyblue', bins=50)
            idx = (np.abs(bins - fav)).argmin()
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
            save_dir = html_dir + 'user/rank/' + screen_name
            if not path.exists(save_dir):
                os.mkdir(save_dir)
            filename = date + '.svg'
            plt.savefig(html_dir + 'user/rank/' + screen_name + '/' + filename)
            plt.close()
         
            total = len(frs[date])
            rank = sorted(frs[date], reverse=True).index(fav)
            percent = int((rank / total) * 100)
         
            imgs.append('''<p style="margin-left: 4em;">{}{} - {}<br>Fav+RT: {}<br>Rank: {} / {} ({}%)</p>
            <img src="{img}" style="max-width: 500px;">
            <img id="{src}" src="{src}">'''.format(get_labels_html(tweet, extra_class='user-label'), date, themes[date]['theme'], fav, rank+1, total, percent, src=screen_name + '/' + filename, img='/precure/1draw-collections/img/{}/{}'.format(tweet['tweet']['user']['id'], tweet['imgs'][0]['filename'])))
     
        with open('rank_template.html') as f:
            template = f.read()
        html = template.format('\n<hr style="margin: 2em;">\n'.join(imgs), last_update=last_update())
         
        with open(html_dir + 'user/rank/{}.html'.format(screen_name), 'w') as f:
            f.write(html)

# admin
def handle_admin_actions():
    with open(admin_actions_file, 'r+') as f:
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
    with open(admin_actions_file) as f:
        actions = yaml.load(f)
        tr = [actions_history_tr(time, item) for time, item in reversed(sorted(actions.items()))]
        tr = '\n\n'.join(tr)

        with open(admin_actions_history_html_file) as f:
            template = f.read()
        html = template.format(tr=tr, last_update=last_update())

        with open(html_dir + 'date/admin-history.html', 'w') as f:
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
        with open(themes_file) as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            themes = yaml.load(f)
        date = get_id_tweet(id)['date']
        action = '「{} - {}」へ移動する'.format(actions['args']['dest'], themes[actions['args']['dest']]['theme'])
        
    args = ['{arg}: {val}'.format(arg=arg, val=val) for arg, val in actions.items()]
    args = ' / '.join(args)
    time = time.strftime('%Y年%m月%d日 %H:%M')
    user = get_id_tweet(id)['tweet']['user']['screen_name']
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
    
    img_path = img_dir + get_id_tweet(id)['tweet']['user']['id_str'] + '/' + get_id_tweet(id)['imgs'][0]['filename']
    subprocess.call(['mogrify', '-rotate', angle, img_path])

def action_remove(id, un=False):
    '''Remove the tweet from the collection.'''
    if not un:
        set_col(id, 'removed', 'deleted')
    else:
        set_col(id, 'removed', False)
    date = get_id_tweet(id)['date']
    generate_date_html(date=date, fetch=False)

def action_move(id, new_date, un=False):
    '''Move the tweet to the other page.'''

    old_date = get_id_tweet(id)['date']

    set_col(id, 'date', new_date)

    # update both date page
    generate_date_html(date=old_date, fetch=False)
    generate_date_html(date=new_date, fetch=False)
    
def action_deny_collection_user(id, un=False):
    '''Add the user of the tweet to deny_collection_user.'''
    with open(ignores_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ignores= yaml.load(f)

        tweet = get_id_tweet(id)
        if not un:
            ignores['deny_collection_user'].append(tweet['tweet']['user']['id'])
            ignores['deny_collection_user'].append(tweet['tweet']['user']['screen_name'])
        else:
            ignores['deny_collection_user'].remove(tweet['tweet']['user']['id'])
            ignores['deny_collection_user'].remove(tweet['tweet']['user']['screen_name'])

        f.seek(0)
        f.truncate()
        yaml.dump(ignores, f, allow_unicode=True)

    generate_date_html_all()

def action_ignore_user(id, un=False):
    '''Add the user of the tweet to deny_collection_user.'''
    with open(ignores_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ignores= yaml.load(f)

        tweet = get_id_tweet(id)
        if not un:
            ignores['ignore_user'].append(tweet['tweet']['user']['id'])
            ignores['ignore_user'].append(tweet['tweet']['user']['screen_name'])
        else:
            ignores['ignore_user'].remove(tweet['tweet']['user']['id'])
            ignores['ignore_user'].remove(tweet['tweet']['user']['screen_name'])

        f.seek(0)
        f.truncate()
        yaml.dump(ignores, f, allow_unicode=True)

    generate_date_html_all()

def import_ids(file):
    with open(file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        ids = yaml.load(f)
    for id in ids:
        retweet_and_record(id=id, retweet=False)

def import_statuses(file):
    with open(file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        statuses = json.load(f)
    
    # filter
    tweets = []
    for status in statuses:
        if status['text'].startswith('RT'):
            tweets.append(status)

    # push to db
    for tweet in tweets:
        retweet_and_record(tweet=tweet, retweet=False, exception=True)

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
        
def import_tweets_from_precure_1draw():
    with open('tweets_of_precure_1draw.json') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        tweets = json.load(f)
    rts = [tweet['retweeted_status'] for tweet in tweets
           if tweet['text'].startswith('RT')]
    for tweet in rts:
        retweet_and_record(tweet=tweet, retweet=False, fetch=False)
    
        
def show_status(id):
    if has_id(id):
        tweet = get_id_tweet(id)
        for key in tweet.keys():
            print('-' * 8)
            print(key)
            pprint(tweet[key])
        print('https://twitter.com/{}/statuses/{}'.format(tweet[1]['user']['screen_name'], tweet[1]['id']))
    else:
        tweet = t.show_status(id=id)
        pprint(tweet)
        print('https://twitter.com/{}/statuses/{}'.format(tweet['user']['screen_name'], tweet['id']))

# deprecated
def db_import_from_json(file):
    with open(file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        tweets = json.load(f)
    con = db_con()
    for id in tweets:
        with con:
            try:
                con.execute('insert into tweets(id, tweet, date, deny_retweet, deny_collection, removed, imgs) values (?,?,?,?,?,?,?)', (tweets[id]['tweet']['id'], tweets[id]['tweet'], tweets[id]['date'],
                                tweets[id]['deny_retweet'], tweets[id]['deny_collection'],
                                tweets[id]['removed'], tweets[id]['imgs']))

            except:
                con.execute('update tweets set tweet=?, date=?, deny_retweet=?, deny_collection=?, removed=?, imgs=? where id=?', (tweets[id]['tweet'], tweets[id]['date'],
                                tweets[id]['deny_retweet'], tweets[id]['deny_collection'],
                                tweets[id]['removed'], tweets[id]['imgs'], tweets[id]['tweet']['id']))
            
def remove_no_url_tweets():
    with open(tweets_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        tweets = json.load(f)
        remove_ids = []
        for id, item in tweets.items():
            if not triger in item['tweet']['text']:
                print('Remove from tweets:', id, item['tweet']['text'])
                remove_ids.append(id)
        for id in remove_ids:
            tweets.pop(id)
        f.seek(0)
        f.truncate()
        json.dump(tweets, f)

def check_db(collect=False):
    '''
    Check if tweets database has proper keys and items.

    Necessary structure:
    id_str: {'tweet': { (data) },
             'date': , (date)
             'deny_retweet': (True | False),
             'deny_collection': (True | False),
             'removed': (False | 'deleted' | 'locked' | 'denied'),
             'imgs': [
                 {'url': (image page url),
                  'img_url': (image url),
                  'filename' (local basename)
                 }*,
             'labels': ['初参加', 'GIF', '10', ... ]
             ]
    }
    '''
    keys = ['tweet', 'date', 'deny_retweet', 'deny_collection', 'removed', 'imgs', 'labels']
    imgs_keys = ['url', 'img_url', 'filename']

    tweets = get_tweets()

    for tweet in tweets:
        for key in keys:
            if key not in tweet.keys():
                print('{}: There is no {}'.format(tweet['id'], key))
            else:
                if not tweet['tweet']:
                    print('{}: "tweet" value is empty.'.format(tweet['id']))
                if not tweet['date']:
                    print('{}: "date" value is empty.'.format(tweet['id']))
                    if collect:
                        date = get_date(tweet['tweet']['created_at'])
                        set_col(tweet['id'], 'date', date)
                        print('Set date:', date)
                if not tweet['deny_retweet'] or not tweet['deny_collection']:
                    if tweet[key] not in [0, 1]:
                        print('{}: "{}" must be bool, but "{}".'.format(tweet['id'], key, tweet[key]))
                if tweet['removed']:
                    if tweet['removed'] not in ['0', 'deleted', 'locked']:
                        print('{}: "removed" must be False, "deleted", or "locked", but "{}".'\
                              .format(tweet['id'], tweet[key]))
                if ['imgs']:
                    for img in tweet['imgs']:
                        for key in imgs_keys:
                            if key not in img:
                                print('{}: img: {}'.format(tweet['id'], img))
                                print('                    "img" does not have "{}" key.'.format(key))
                                if collect:
                                    store_image(tweet['id'])

def fix_db():
    tweets = get_tweets()
    for tweet in tweets:
        if tweet['removed'] == '0':
            if not tweet['imgs']:
                print('-' * 16)
                print('Fix imgs', tweet['id'])
                store_image(tweet['id'])
            if not tweet['labels']:
                print('-' * 16)
                print('Fix labels', tweet['id'])
                update_labels(tweet['id'])
            
def follow_back():
    '''Follow back all the followers who are not followed.'''
    followers = t.get_followers_list()['users']
    for user in followers:
        if not user['following']:
            t.create_friendship(screen_name=user['screen_name'])
            print('Follow back a new user:', user['screen_name'])

def api_test():
    '''Test code for the time to revive API rate. -> max time = 15 min'''
    empty = False
    while True:
        api = t.get_application_rate_limit_status()
        api_remaining = api['resources']['statuses']['/statuses/show/:id']['remaining']
        api_limit = api['resources']['statuses']['/statuses/show/:id']['limit']
        for i in range(30):
            try:
                t.show_status(id=471760689229733889)
                if empty:
                    print(('{} {}/{}: ' + '|' * (api_remaining // 2)).format(datetime.datetime.now().time().strftime('%H:%M:%S'), api_remaining, api_limit))
                    empty = False
            except TwythonError:
                empty = True
                
        print(('{} {}/{}: ' + '|' * (api_remaining // 2)).format(datetime.datetime.now().time().strftime('%H:%M:%S'), api_remaining, api_limit))

        time.sleep(60)

if __name__ == '__main__':
    html_dir = 'html/'
    img_dir = 'img/'

    tweets_file = 'tweets.json'
    themes_file = 'themes.yaml'

    ignores_file = 'ignores.yaml'

    date_que_file = 'date_que.yaml'

    admin_actions_file = 'html/date/admin_actions.yaml'
    admin_actions_history_html_file = 'admin_actions_history_template.html'

    index_html_template_file = 'index_template.html'
    index_en_html_template_file = 'index_en_template.html'
    date_html_template_file = 'date_template.html'
    tweet_html_template_file = 'tweet_template.html'
    tweet_admin_html_template_file = 'tweet_admin_template.html'
    user_html_template_file = 'user_template.html'
    
    ribbon_names = ['', 'admin-']

    t = auth()
    stream = stream_auth()
    
    hash_tags = ['プリキュア版深夜の真剣お絵描き60分一本勝負', # first tag is default
                 'プリキュア版深夜の真剣お絵描き60秒一本勝負']
    triger = 'http'

    if len(sys.argv) == 1:
        print('''Usage: precure_1draw.py 'func()'
functions:
  auto_retweet_stream()
  auto_retweet_rest(past=3, retweet=True)
  retweet_and_record(tweet=False, id=False, retweet=True, fetch=True, exception=False)
  record_user(screen_name)
  store_image(id)
  make_symlinks_to_img_dir()
  set_col(id, col, val)
  has_id(id)
  upsert_tweet(id, tweet, date, deny_retweet, deny_collection, exception)
  get_id_tweet(id)
  destroy_id_tweet(id)
  get_tweets(date='', screen_name='')
  print_tweet(id=0, tweet=None)
  print_all_tweets()
  store_image_all()
  store_image_date(date='')
  get_search_remaining()
  get_show_status_remaining()
  update_themes()
  update_user_nums()
  print_first_participants()
  print_user_work_number(screen_name)
  get_user_work_number(id)
  update_labels(id, force=False)
  get_id_all()
  update_labels_all()
  get_labels_html(tweet, extra_class='')
  generate_index_html()
  generate_date_html(date='', fetch=True)
  generate_date_html_circulate()
  generate_date_html_all()
  generate_user_html_all()
  handle_admin_action()
  action_log(action)
  actions_log_html_tr(time, actions)
  generate_admin_actions_log_html()
  action_add_exception(id)
  action_rotate(id, angle)
  action_remove(id, un=False)
  action_move(id, new_date, un=False)
  action_deny_user(id, un=False)
  action_ignore_user(id, un=False)
  import_ids(file)
  import_statuses(file)
  show_status(id)
  db_import_from_json(file)
  remove_no_url_tweets()
  check_db(collect=False)
  fix_db()
  follow_back()''')
    elif len(sys.argv) == 2:
        eval(sys.argv[1]) # run given name function


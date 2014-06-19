#!/usr/bin/env python3
# precure-1draw.py
#   - Retweet all the tweets with the hashtag and image(including 'http')
#   - Store tweets data
#   - Generate html gallery which show tweets with images
import re
import sys
import os
from glob import glob
import difflib
import fcntl
import time
import locale
import datetime
import pytz
import yaml
import sqlite3
from os import path
from dateutil.parser import parse
from io import BytesIO
from pprint import pprint
import subprocess

import simplejson as json
import requests
from bs4 import BeautifulSoup
from twython import Twython
from twython import TwythonStreamer
from twython import TwythonError
from PIL import Image

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
                retweet_and_record(tweet)
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
    max_id=''
    tweets = []
    for i in range(past):
        res = t.search(q='#' + hash_tags[0] + ' -RT', count=100, result_type='recent', max_id=max_id)
        res = res['statuses']
        max_id = res[-1]['id_str']
        for tweet in res:
            tweets.append(tweet)
        time.sleep(10)

    for tweet in reversed(tweets):
        if not has_id(tweet['id']):
            if retweet:
                retweet_and_record(tweet=tweet)
            else:
                retweet_and_record(tweet=tweet, retweet=False)

# retweet & record
def retweet_and_record(tweet=False, id=False, retweet=True, fetch=True, exception=False):
    '''Retweet and record the tweet.'''
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

        # date
        if not ('date' in tweet.keys() and tweet['date'] == '0-misc'):   # avoid overwrite misc category
            date = get_date(tweet['tweet']['created_at'])
        else:
            date = tweet['date']

        # deny_retweet
        if (tweet['tweet']['user']['screen_name'] in ignores['deny_retweet_user']) or (tweet['tweet']['user']['id'] in ignores['deny_retweet_user']):
            deny_retweet = True
        else:
            deny_retweet = False
            if retweet and not has_id(tweet['tweet']['id']):
                try:
                    t.retweet(id=tweet['tweet']['id'])
                except TwythonError as e:
                    if e.error_code == 403:
                        print('Double retweet:', tweet['tweet']['id'])

        # deny_collection
        if (tweet['tweet']['user']['screen_name'] in ignores['deny_collection_user']) or (tweet['tweet']['user']['id'] in ignores['deny_collection_user']):
            deny_collection = True
        else:
            deny_collection = False

        # exception
        if exception or (not new and tweet['exception']):
            exception = False
            print('Accepted by exception')
        else:
            exception = False
            
        # update
        upsert_tweet(tweet['tweet']['id'], tweet['tweet'], date, deny_retweet, deny_collection, exception)

        if 'imgs' not in tweet.keys():
            store_image(tweet['tweet']['id'])

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
        print('-' * 16)
        print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
        print(hit)
        print_tweet(None, tweet=tweet)
        return False
    else:
        return True
    
# image
def store_image(id):
    tweet = get_id_tweet(id)
    urls = []
    if 'media' in tweet['tweet']['entities']: # tweet has official image 
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
        elif re.search(r'((jpeg)|(jpg)|(png)|(gif))(.*)$', url):
            img_url = url
        elif 'pixiv' in url:
            headers = {'referer': 'http://www.pixiv.net/'}
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup('img')[1]['src']
        elif 'togetter.com' in url:
            img_url = filename = False
        elif re.search(r'twitter.com/.+?/status/', url):
            continue
        else:
            img_url = filename = False
        if img_url:
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
            if not os.path.exists(save_dir):
                os.mkdir(save_dir)
            with open(save_dir + filename, 'wb') as f2:
                f2.write(img)
                print('Downloaded: {} -> {} -> {}'.format(url, img_url, save_dir + filename))

        imgs.append({'url': url, 'img_url': img_url, 'filename': filename})
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

def upsert_tweet(id, tweet, date, deny_retweet, deny_collection, exception):
    con = db_con()
    try:
        with con:
            con.execute('insert into tweets(id, tweet, date, deny_retweet, deny_collection, exception) values (?,?,?,?,?,?)', (id, tweet, date, deny_retweet, deny_collection, exception))
            print('-' * 16)
            print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
            print('Add a new record: {} deny_retweet: {}, deny_collection: {}'.format(id, deny_retweet, deny_collection))
    except:
        try:
            with con:
                con.execute('update tweets set tweet=?, date=?, deny_retweet=?, deny_collection=?, exception=? where id=?', (tweet, date, deny_retweet, deny_collection, exception, id))
                # print('-' * 16)
                # print('Update: {} deny_retweet: {}, deny_collection: {}'.format(id, deny_retweet, deny_collection))
        except sqlite3.Error as e:
            print(e)
            time.sleep(5)

def get_id_tweet(id):
    con = db_con()
    return con.execute("select * from tweets where id=?", (id, )).fetchone()

def get_tweets(date='', screen_name=''):
    con = db_con()
    if date:
        ts = [t for t in con.execute('select * from tweets where date=? order by id', (date, ))]
    elif screen_name:
        for tweet in con.execute('select * from tweets order by id'):
            if tweet['tweet']['user']['screen_name'] == screen_name:
                user_id = tweet['tweet']['user']['id']
                break
        ts = [t for t in con.execute('select * from tweets') if t['tweet']['user']['id'] == user_id]
    else:
        ts = [t for t in con.execute('select * from tweets order by id')]
    return ts

def print_tweet(id, tweet=None):
    if id:
        tweet = get_id_tweet(id)
    print(tweet['tweet']['id']) # not tweet['id'] because tweet can have only 'tweet' key
    print('https://twitter.com/{}/status/{}'.format(tweet['tweet']['user']['screen_name'], tweet['tweet']['id']))
    print('{} (@{})'.format(tweet['tweet']['user']['name'], tweet['tweet']['user']['screen_name']))
    print(tweet['tweet']['text'])

def print_all_tweets():
    ts = get_tweets()
    for i in ts:
        print('{} {} {}/{}/{} {}({}) | {}'.format(i['id'], i['date'], i['removed'], i['deny_collection'], i['deny_retweet'], i['tweet']['user']['name'], i['tweet']['user']['screen_name'], i['tweet']['text'][:10]))

def redownload_all_images():
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
                match = re.findall('(?:“|”)(.+?)(?:“|”)', tweet['text'])
                if match:
                    themes[date] = {}
                    themes[date]['theme'] = ' / '.join(match)
                    themes[date]['num'] = 0

        for date in themes:
            # con = db_con()
            # con.execute("select * from tweets where date=?", (date, )).fetchall()
            # themes[date]['num'] = len([item for item in tweets if item['date'] == date])
            themes[date]['num'] = len(get_tweets(date))
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
        
    with open(themes_file_admin, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(themes, f, ensure_ascii=False)

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
                
def update_user_nums():
    with open(themes_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        themes = yaml.load(f)

        users = []
        for date in sorted(themes):
            if date != '0-misc':
                tweets = get_tweets(date)
                users.extend([t['tweet']['user']['id'] for t in tweets])
                themes[date]['user_num'] = len(set(users))
        f.seek(0)
        f.truncate()
        yaml.dump(themes, f, allow_unicode=True)
        
def last_update():
    return datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')
        
def generate_index_html():
    locale.setlocale(locale.LC_ALL, '')
    with open(index_html_template_file) as f:
        index_html_template = f.read()
    with open(themes_file) as f:
        themes = yaml.load(f)
    for ribbon_name in ribbon_names:
        trs = []
        even = True
        
        for num, (date, item) in enumerate(reversed(sorted(themes.items()))):
            if even:
                row = 'even'
                even = False
            else:
                row = 'odd'
                even = True

            num = len(themes) - num -1

            if date == '0-misc':
                date_str = '-'
            else:
                date_str = parse(date).strftime('<span class="year">%Y年</span>%m月%d日(%a)')

            if path.exists(html_dir + 'date/' + ribbon_name + date + '.html'):
                link = '<a href="date/{ribbon_name}{date}.html">{theme}</a>'.format(ribbon_name=ribbon_name, date=date, theme=item['theme'])
            else:
                link = item['theme']

            if item['num'] == 0:
                work_num = ''
            else:
                work_num = int(item['num'])

            if item['togetter']:
                togetter = '<a href="{}"><i class="fa fa-square fa-lg" style="color: #7fc6bc" title="Togetter のまとめを見る"></i></a>'.format(item['togetter'])
            else:
                togetter = ''

            tr = '''<tr class ="{row}">
            <td class="num">#{num:2d}</td>
            <td class="date">{date_str}</td>
            <td class="theme">{link}</td>
            <td class="work_num">{work_num}</td>
            <td class="togetter">
              {togetter}
            </td>
            </tr>'''.format(row=row, num=num, date_str=date_str, link=link, theme=item['theme'], work_num=work_num, togetter=togetter)
            trs.append(tr)
        html = index_html_template.format(ribbon_name=ribbon_name[:-1],
                                          list=''.join(trs),
                                          last_update=last_update())
             
        with open(html_dir + ribbon_name + 'index.html', 'w') as f:
            f.write(html)

def generate_date_html(date='', fetch=True):
    '''Generate a html of the specific date.'''
    if not date:
        date = get_date()

    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)
    theme = themes[date]['theme']

    with open(date_html_template_file) as f1:
        date_html_template = f1.read()
    with open(tweet_html_template_file) as f1:
        tweet_html_template = f1.read()
    with open(tweet_admin_html_template_file) as f1:
        tweet_admin_html_template = f1.read()

    # generate html
    date_tweets = get_tweets(date)
    tweets = []
    for tweet in date_tweets:
        if (not tweet['deny_collection']) and (tweet['removed'] == '0') and (not tweet['tweet']['user']['screen_name'] == 'precure_1draw'): # condition to collection
            tweets.append(tweet)
    if not tweets:
        print('There is no tweet of the day.')
        return

    if date == '0-misc': # if misc, new to old order
        tweets = reversed(tweets)
    
    tweet_htmls = {}
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

        linked_text = tweet['tweet']['text'].replace('#プリキュア版深夜の真剣お絵描き60分一本勝負', r'<a href="https://twitter.com/search?q=%23%E3%83%97%E3%83%AA%E3%82%AD%E3%83%A5%E3%82%A2%E7%89%88%E6%B7%B1%E5%A4%9C%E3%81%AE%E7%9C%9F%E5%89%A3%E3%81%8A%E7%B5%B5%E6%8F%8F%E3%81%8D60%E5%88%86%E4%B8%80%E6%9C%AC%E5%8B%9D%E8%B2%A0&amp;src=hash" class="hashtag customisable">#<b>プリキュア版深夜の真剣お絵描き60分一本勝負</b></a>')

        # replace t.co to display_url and linkify
        if 'media' in tweet['tweet']['entities']: # tweet has official image
            key = 'media'
        elif 'urls' in tweet['tweet']['entities']:
            key = 'urls'
        else:
            continue
        for urls in tweet['tweet']['entities'][key]:
            linked_text = linked_text.replace(urls['url'], '<a href="{}">{}</a>'.format(urls['expanded_url'], urls['display_url']))

        imgs = []
        for img in tweet['imgs']:
            if img['filename']:
                img_src = '../' + img_dir + tweet['tweet']['user']['id_str'] + '/' + img['filename']
                img_style = ''
            else: # no image
                img_src = ''
                img_style='display: none;'
            imgs.append('<img class="illust lazy" src="{img_src}" title="ツイートを見る" style="{img_style}">'.format(img_src=img_src, img_style=img_style))
        imgs = '\n\n'.join(imgs)

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

    if date == '0-misc':
        date_str = ''
        num = ''
    else:
        date_str = parse(date).strftime('%Y年%m月%d日')
        num = '第{}回'.format(sorted(themes).index(date))
    for ribbon_name in ribbon_names:
        tweets_html = '\n\n'.join(tweet_htmls[ribbon_name])
        html = date_html_template.format(ribbon_name=ribbon_name[:-1],
                                         num=num,
                                         date=date,
                                         date_str=date_str,
                                         theme=theme,
                                         tweets=tweets_html,
                                         last_update=last_update())
                                         
        with open(html_dir + ribbon_name + date + '.html', 'w') as f:
            f.write(html)

def generate_date_html_circulate():
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
    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)

    for date in sorted(themes):
        print('Updating:', date)
        generate_date_html(date=date, fetch=False)

def generate_user_html(screen_name):
    with open(themes_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        themes = yaml.load(f)
    with open(user_html_template_file) as f:
        template = f.read()
    tweets = get_tweets(screen_name=screen_name)
    name = tweets[0]['tweet']['user']['name']
    imgs = []
    for tweet in reversed(tweets):
        for img in tweet['imgs']:
            img_path = img_dir + tweet['tweet']['user']['id_str'] + '/' + img['filename']
            try:
                caption = '{date}<br>{theme}'.format(date=tweet['date'], theme=themes[tweet['date']]['theme'])
            except:
                pprint(tweet['tweet'])
            link = 'https://twitter.com/{}/status/{}'.format(tweet['tweet']['user']['screen_name'] ,tweet['id'])
            imgs.append('<a href={link}><figure><img class="gallery" src="{src}"><figcaption>{caption}</figcaption></figure></a>'.format(link=link, src=img_path, caption=caption))

    html = template.format(name='{} (@{})'.format(name, screen_name), imgs='\n\n'.join(imgs), last_update=last_update())
    with open(html_dir + 'user/' + screen_name + '.html', 'w') as f:
        f.write(html)

def generate_user_html_all():
    with open(ignores_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        ignores = yaml.load(f)
    tweets = get_tweets()
    users = [tweet['tweet']['user']['screen_name'] for tweet in tweets
             if tweet['tweet']['user']['screen_name'] not in ignores['deny_collection_user']
             and tweet['tweet']['user']['id'] not in ignores['deny_collection_user']]
    for user in users:
        generate_user_html(user)

# admin
def handle_admin_action():
    with open(admin_actions_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        actions = yaml.load(f)
        while actions:
            action = actions.pop()
            if action['action'] == 'rotate':
                action_rotate(action['id'], action['angle'])
            elif action['action'] == 'remove':
                action_remove(action['id'])
            elif action['action'] == 'move':
                action_move(action['id'], action['date'])
            elif action['action'] == 'ignore_user':
                action_deny_user(action['id'])
            elif action['action'] == 'ignore_user':
                action_ignore_user(action['id'])
            action_log(action)
            f.seek(0)
            f.truncate()
            yaml.dump(actions, f)

def action_log(action):
    '''Log a admin action.'''
    with open(admin_actions_log_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        log = yaml.load(f)
        log[datetime.datetime.now()] = action
        f.seek(0)
        f.truncate()
        yaml.dump(log, f, allow_unicode=True)

def actions_log_html_tr(time, actions):
    id = actions.pop('id')
    action = actions.pop('action')
    args = ['{arg}: {val}'.format(arg=arg, val=val) for arg, val in actions.items()]
    args = ' / '.join(args)
    tr = '''<tr>
  <td class="time">{time}</td>
  <td class="id">{id}</td>
  <td class="action">{action}</td>
  <td class="args">{args}</td>
</tr>'''.format(time=time, id=id, action=action, args=args)
    return tr

def generate_admin_actions_log_html():
    with open(admin_actions_log_file) as f:
        logs = yaml.load(f)
        logs_html_tr = [actions_log_html_tr(time,actions) for time, actions in logs.items()]
        logs_html_tr = '\n\n'.join(logs_html_tr)

        with open(admin_actions_log_html_template_file) as f:
            admin_actions_log_html_template = f.read()
        html = admin_actions_log_html_template.format(tr=logs_html_tr, last_update=last_update)

        with open(html_dir + 'admin-actions-history.html', 'w') as f:
            f.write(html )
                
# global action
def action_add_exception(id):
    '''Add a tweet by id as a exception.'''
    retweet_and_record(id=id, retweet=False, exception=True)
    
# local action
def action_rotate(id, angle):
    '''Rotate the image of the tweet.'''
    if angle == 'left':
        angle = -90
    elif angle == 'right':
        angle = 90
    
    img_path = img_dir + get_id_tweet(id)['tweet']['user']['id_str'] + get_id_tweet(id)['imgs']['filename']
    subprocess.call(['mogrify', '-rotate', angle, img_path])

def action_remove(id, un=False):
    '''Remove the tweet from the collection.'''
    if not un:
        set(id, 'removed', 'deleted')
    else:
        set(id, 'removed', False)

def action_move(id, date, un=False):
    '''Move the tweet to the other page.'''
    set_col(id, 'date', date)
    
def action_deny_user(id, un=False):
    '''Add the user of the tweet to deny_collection_user.'''
    with open(ignores_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ignores= yaml.load(f)

        if not un:
            ignores['deny_collection'].append(get_id_tweet(id)['user']['id'])
            ignores['deny_collection'].append(get_id_tweet(id)['user']['screen_name'])
        else:
            ignores['deny_collection'].remove(get_id_tweet(id)['user']['id'])
            ignores['deny_collection'].remove(get_id_tweet(id)['user']['screen_name'])

        f.seek(0)
        f.truncate()
        yaml.dump(ignores, f, allow_unicode=True)

def action_ignore_user(id, un=False):
    '''Add the user of the tweet to deny_collection_user.'''
    with open(tweets_file) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        tweets = yaml.load(f)
    with open(ignores_file, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ignores= yaml.load(f)

        if not un:
            ignores['ignore_user'].append(tweets[id]['user']['id'])
            ignores['ignore_user'].append(tweets[id]['user']['screen_name'])
        else:
            ignores['ignore_user'].remove(tweets[id]['user']['id'])
            ignores['ignore_user'].remove(tweets[id]['user']['screen_name'])

        f.seek(0)
        f.truncate()
        yaml.dump(ignores, f, allow_unicode=True)

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

def get_tweets_from_precure_1draw():
    tweets = []
    max_id=None
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
        pprint([x for x in get_id_tweet(id)])
    else:
        pprint(t.show_status(id=id))

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
                 }*
             ]
    }
    '''
    keys = ['tweet', 'date', 'deny_retweet', 'deny_collection', 'removed', 'imgs']
    imgs_keys = ['url', 'img_url', 'filename']

    tweets = get_tweets()

    for tweet in tweets:
        for key in keys:
            if key in tweet.keys():
                print('{}: does not have "{}" key.'.format(id, key))
                if collect:
                    if key == 'imgs':
                        store_image(tweet['id'])
                    elif key == 'date':
                        date = get_date(tweet['tweet']['created_at'])
                        set_col(tweet['id'], 'date', date)
                        print('Set date:', date)
            else:
                if not tweet['tweet']:
                    print('{}: "tweet" value is empty.'.format(id))
                if not tweet['date']:
                    print('{}: "date" value is empty.'.format(id))
                if key == 'deny_retweet' or key == 'deny_collection':
                    if tweet[key] not in [0, 1]:
                        print('{}: "{}" must be bool, but "{}".'.format(id, key, tweet[key]))
                if key == 'removed':
                    if tweet['removed'] not in ['0', 'deleted', 'locked']:
                        print('{}: "removed" must be False, "deleted", or "locked", but "{}".'\
                              .format(id, tweet[key]))
                if key == 'imgs':
                    for img in tweet['imgs']:
                        for key in imgs_keys:
                            if key not in img:
                                print('{}: img: {}'.format(id, img))
                                print('                    "img" does not have "{}" key.'.format(key))
            
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
    themes_file_admin = html_dir + 'themes.json'

    ignores_file = 'ignores.yaml'

    date_que_file = 'date_que.yaml'

    admin_actions_file = 'admin_actions.yaml'
    admin_actions_log_file = 'admin_actions_log.yaml'
    admin_actions_log_html_template_file = 'admin_actions_log_template.html'

    index_html_template_file = 'index_template.html'
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

    if len(sys.argv) == 2:
        eval(sys.argv[1]) # run given name function


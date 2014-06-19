#!/usr/bin/env python3
# Script to get all the tweet ids
# from the official collection on the togetter
import re
import yaml
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import WebDriverException

url_base = 'http://togetter.com'
url = 'http://togetter.com/id/precure_1draw'

pages = []
ids = []

# get urls
browser = webdriver.Chrome()
for i in range(2):
    browser.get(url)
    soup = BeautifulSoup(browser.page_source)

    for a in soup(class_='simple_list')[0](class_='more_btn'):
        pages.append(a['href'])

    next = soup(rel='next')
    if next:
        url = url_base + next[0]['href']
    else:
        break
    print('pages', pages)

for page in pages:
    browser.get(page)
    print('Getting', page, browser.title)
    time.sleep(5)
    try:
        browser.find_element_by_partial_link_text('残りを読む').click()
        print('Click ramainings button')
    except WebDriverException as e:
        print(e)
    time.sleep(5)

    soup = BeautifulSoup(browser.page_source)
    links = [a['href'] for a in soup(class_='pagenation')[0]('a') if a.has_attr('class')]
    print('get links', links)
    for link in links:
        next = url_base + link
        try:
            browser.get(next)
            print('Getting', next)
        except WebDriverException as e:
            print(e)
        time.sleep(5)
        
        soup = BeautifulSoup(browser.page_source)
        page_ids = [id for id in [re.search('\d+$', a['href']).group() for a in soup(class_='timestamp')]]
        for page_id in page_ids:
            if page_id in ids:
                print(page_id, 'is in ids')
        ids.extend(page_ids)
        print('Add', len(page_ids), 'ids')
        print(page_ids)

with open('togetter.yaml', 'w') as f:
    yaml.dump(ids, f)
    print(ids)
    print('Got', len(ids), 'ids')

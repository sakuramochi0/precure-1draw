#!/usr/bin/env python3
# Script to get all the tweet ids
# from the topsy archive
# Note: unfortunately, this cannot get all the tweet
import re
import yaml
from selenium import webdriver
from bs4 import BeautifulSoup

url_base = 'http://topsy.com/s?q=%23%E3%83%97%E3%83%AA%E3%82%AD%E3%83%A5%E3%82%A2%E7%89%88%E6%B7%B1%E5%A4%9C%E3%81%AE%E7%9C%9F%E5%89%A3%E3%81%8A%E7%B5%B5%E6%8F%8F%E3%81%8D60%E5%88%86%E4%B8%80%E6%9C%AC%E5%8B%9D%E8%B2%A0%20-RT&sort=-date&mintime='
mintime = '1402153575'
url = url_base + mintime

ids = []
for i in range(1, 160):
    browser = webdriver.Chrome()
    browser.get(url)
    soup = BeautifulSoup(browser.page_source)
    browser.close()
    get_ids = [re.search(r'\d+$', i.parent.get('href')).group(0) for i in soup(class_='relative-date')]
    ids.extend(get_ids)
    ids = list(set(ids)) # to make ids unique
    mintime = soup(class_='relative-date')[-1].get('data-timestamp')
    url = url_base + mintime
    print('{}回目: {}, {}'.format(i, get_ids[-1], mintime))

    with open('topsy.yml', 'w') as f:
        yaml.dump(ids, f)
